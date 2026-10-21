"""
JLCPCB Parts Database Manager

Manages local SQLite database of JLCPCB parts for fast searching
and component selection.
"""

import os
import sqlite3
import json
import logging
from pathlib import Path
from typing import List, Dict, Optional
from datetime import datetime

logger = logging.getLogger('kicad_interface')


class JLCPCBPartsManager:
    """
    Manages local database of JLCPCB parts

    Provides fast parametric search, filtering, and package-to-footprint mapping.
    """

    def __init__(self, db_path: Optional[str] = None):
        """
        Initialize parts database manager

        Args:
            db_path: Path to SQLite database file (default: data/jlcpcb_parts.db)
        """
        if db_path is None:
            # Default to data directory in project root
            project_root = Path(__file__).parent.parent.parent
            data_dir = project_root / "data"
            data_dir.mkdir(exist_ok=True)
            db_path = str(data_dir / "jlcpcb_parts.db")

        self.db_path = db_path
        self.conn = None
        self._init_database()

    def _init_database(self):
        """Initialize SQLite database with schema"""
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row  # Return rows as dicts

        cursor = self.conn.cursor()

        # Create components table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS components (
                lcsc TEXT PRIMARY KEY,
                category TEXT,
                subcategory TEXT,
                mfr_part TEXT,
                package TEXT,
                solder_joints INTEGER,
                manufacturer TEXT,
                library_type TEXT,
                description TEXT,
                datasheet TEXT,
                stock INTEGER,
                price_json TEXT,
                last_updated INTEGER
            )
        ''')

        # Create indexes for fast searching
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_category ON components(category, subcategory)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_package ON components(package)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_manufacturer ON components(manufacturer)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_library_type ON components(library_type)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_mfr_part ON components(mfr_part)')

        # Full-text search index for descriptions
        cursor.execute('''
            CREATE VIRTUAL TABLE IF NOT EXISTS components_fts USING fts5(
                lcsc,
                description,
                mfr_part,
                manufacturer,
                content=components
            )
        ''')

        self.conn.commit()
        logger.info(f"Initialized JLCPCB parts database at {self.db_path}")

    def import_parts(self, parts: List[Dict], progress_callback=None):
        """
        Import parts into database from JLCPCB API response

        Args:
            parts: List of part dicts from JLCPCB API
            progress_callback: Optional callback(current, total, message)
        """
        cursor = self.conn.cursor()
        imported = 0
        skipped = 0

        for i, part in enumerate(parts):
            try:
                # Extract price breaks
                price_json = json.dumps(part.get('prices', []))

                # Determine library type
                library_type = self._determine_library_type(part)

                cursor.execute('''
                    INSERT OR REPLACE INTO components (
                        lcsc, category, subcategory, mfr_part, package,
                        solder_joints, manufacturer, library_type, description,
                        datasheet, stock, price_json, last_updated
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    part.get('componentCode'),  # lcsc
                    part.get('firstSortName'),  # category
                    part.get('secondSortName'),  # subcategory
                    part.get('componentModelEn'),  # mfr_part
                    part.get('componentSpecificationEn'),  # package
                    part.get('soldPoint'),  # solder_joints
                    part.get('componentBrandEn'),  # manufacturer
                    library_type,  # library_type
                    part.get('describe'),  # description
                    part.get('dataManualUrl'),  # datasheet
                    part.get('stockCount', 0),  # stock
                    price_json,  # price_json
                    int(datetime.now().timestamp())  # last_updated
                ))

                imported += 1

                if progress_callback and (i + 1) % 1000 == 0:
                    progress_callback(i + 1, len(parts), f"Imported {imported} parts...")

            except Exception as e:
                logger.error(f"Error importing part {part.get('componentCode')}: {e}")
                skipped += 1

        # Update FTS index
        cursor.execute('''
            INSERT INTO components_fts(components_fts, rowid, lcsc, description, mfr_part, manufacturer)
            SELECT 'rebuild', rowid, lcsc, description, mfr_part, manufacturer FROM components
        ''')

        self.conn.commit()
        logger.info(f"Import complete: {imported} parts imported, {skipped} skipped")

    def _determine_library_type(self, part: Dict) -> str:
        """Determine if part is Basic, Extended, or Preferred"""
        # JLCPCB API should provide this, but if not, we infer from assembly type
        assembly_type = part.get('assemblyType', '')

        if 'Basic' in assembly_type or part.get('libraryType') == 'base':
            return 'Basic'
        elif 'Extended' in assembly_type:
            return 'Extended'
        elif 'Prefer' in assembly_type:
            return 'Preferred'
        else:
            return 'Extended'  # Default to Extended

    def import_jlcsearch_parts(self, parts: List[Dict], progress_callback=None):
        """
        Import parts into database from JLCSearch API response

        Args:
            parts: List of part dicts from JLCSearch API
            progress_callback: Optional callback(current, total, message)
        """
        cursor = self.conn.cursor()
        imported = 0
        skipped = 0

        for i, part in enumerate(parts):
            try:
                # JLCSearch format is different from official API
                # LCSC is an integer, we need to add 'C' prefix
                lcsc = part.get('lcsc')
                if isinstance(lcsc, int):
                    lcsc = f"C{lcsc}"

                # Build price JSON from jlcsearch single price
                price = part.get('price') or part.get('price1')
                price_json = json.dumps([{"qty": 1, "price": price}] if price else [])

                # Determine library type from is_basic flag
                library_type = 'Basic' if part.get('is_basic') else 'Extended'
                if part.get('is_preferred'):
                    library_type = 'Preferred'

                # Extract description from various fields
                description_parts = []
                if 'resistance' in part:
                    description_parts.append(f"{part['resistance']}Ω")
                if 'capacitance' in part:
                    description_parts.append(f"{part['capacitance']}F")
                if 'tolerance_fraction' in part:
                    tol = part['tolerance_fraction'] * 100
                    description_parts.append(f"±{tol}%")
                if 'power_watts' in part:
                    description_parts.append(f"{part['power_watts']}mW")
                if 'voltage' in part:
                    description_parts.append(f"{part['voltage']}V")

                description = part.get('description', ' '.join(description_parts))

                cursor.execute('''
                    INSERT OR REPLACE INTO components (
                        lcsc, category, subcategory, mfr_part, package,
                        solder_joints, manufacturer, library_type, description,
                        datasheet, stock, price_json, last_updated
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    lcsc,  # lcsc with C prefix
                    part.get('category', ''),  # category
                    part.get('subcategory', ''),  # subcategory
                    part.get('mfr', ''),  # mfr_part
                    part.get('package', ''),  # package
                    0,  # solder_joints (not in jlcsearch)
                    part.get('manufacturer', ''),  # manufacturer
                    library_type,  # library_type
                    description,  # description
                    '',  # datasheet (not in jlcsearch)
                    part.get('stock', 0),  # stock
                    price_json,  # price_json
                    int(datetime.now().timestamp())  # last_updated
                ))

                imported += 1

                if progress_callback and (i + 1) % 1000 == 0:
                    progress_callback(i + 1, len(parts), f"Imported {imported} parts...")

            except Exception as e:
                logger.error(f"Error importing part {part.get('lcsc')}: {e}")
                skipped += 1

        # Update FTS index
        cursor.execute('''
            INSERT INTO components_fts(components_fts)
            VALUES('rebuild')
        ''')

        self.conn.commit()
        logger.info(f"Import complete: {imported} parts imported, {skipped} skipped")

    def search_parts(
        self,
        query: Optional[str] = None,
        category: Optional[str] = None,
        package: Optional[str] = None,
        library_type: Optional[str] = None,
        manufacturer: Optional[str] = None,
        in_stock: bool = True,
        limit: int = 20
    ) -> List[Dict]:
        """
        Search for parts with filters

        Args:
            query: Free-text search (searches description, mfr part, LCSC)
            category: Filter by category name
            package: Filter by package type
            library_type: Filter by "Basic", "Extended", or "Preferred"
            manufacturer: Filter by manufacturer name
            in_stock: Only return parts with stock > 0
            limit: Maximum number of results

        Returns:
            List of matching parts
        """
        cursor = self.conn.cursor()

        # Build query
        sql_parts = ["SELECT * FROM components WHERE 1=1"]
        params = []

        if query:
            # Use FTS for text search
            # Add prefix wildcard to each term for partial matching
            # (e.g., "BQ25895" becomes "BQ25895*" so FTS matches "BQ25895RTWR")
            fts_query = " ".join(
                f"{term}*" if not term.endswith("*") else term
                for term in query.strip().split()
            )
            sql_parts.append('''
                AND lcsc IN (
                    SELECT lcsc FROM components_fts
                    WHERE components_fts MATCH ?
                )
            ''')
            params.append(fts_query)

        if category:
            sql_parts.append("AND category LIKE ?")
            params.append(f"%{category}%")

        if package:
            sql_parts.append("AND package LIKE ?")
            params.append(f"%{package}%")

        if library_type:
            sql_parts.append("AND library_type = ?")
            params.append(library_type)

        if manufacturer:
            sql_parts.append("AND manufacturer LIKE ?")
            params.append(f"%{manufacturer}%")

        if in_stock:
            sql_parts.append("AND stock > 0")

        sql_parts.append("LIMIT ?")
        params.append(limit)

        sql = " ".join(sql_parts)

        try:
            cursor.execute(sql, params)
            rows = cursor.fetchall()
            return [dict(row) for row in rows]
        except Exception as e:
            logger.error(f"Search error: {e}")
            return []

    def get_part_info(self, lcsc_number: str) -> Optional[Dict]:
        """
        Get detailed information for specific LCSC part

        Args:
            lcsc_number: LCSC part number (e.g., "C25804")

        Returns:
            Part info dict or None if not found
        """
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM components WHERE lcsc = ?", (lcsc_number,))
        row = cursor.fetchone()

        if row:
            part = dict(row)
            # Parse price JSON
            if part.get('price_json'):
                try:
                    part['price_breaks'] = json.loads(part['price_json'])
                except (json.JSONDecodeError, TypeError, ValueError):
                    part['price_breaks'] = []
            return part
        return None

    def get_database_stats(self) -> Dict:
        """Get statistics about the database"""
        cursor = self.conn.cursor()

        cursor.execute("SELECT COUNT(*) as total FROM components")
        total = cursor.fetchone()['total']

        cursor.execute("SELECT COUNT(*) as basic FROM components WHERE library_type = 'Basic'")
        basic = cursor.fetchone()['basic']

        cursor.execute("SELECT COUNT(*) as extended FROM components WHERE library_type = 'Extended'")
        extended = cursor.fetchone()['extended']

        cursor.execute("SELECT COUNT(*) as in_stock FROM components WHERE stock > 0")
        in_stock = cursor.fetchone()['in_stock']

        return {
            'total_parts': total,
            'basic_parts': basic,
            'extended_parts': extended,
            'in_stock': in_stock,
            'db_path': self.db_path
        }

    def map_package_to_footprint(self, package: str) -> List[str]:
        """
        Map JLCPCB package name to KiCAD footprint(s)

        Args:
            package: JLCPCB package name (e.g., "0603", "SOT-23")

        Returns:
            List of possible KiCAD footprint library refs
        """
        mappings = {
            # Chip resistors / capacitors / inductors / LEDs
            "0201": [
                "Resistor_SMD:R_0201_0603Metric",
                "Capacitor_SMD:C_0201_0603Metric",
            ],
            "0402": [
                "Resistor_SMD:R_0402_1005Metric",
                "Capacitor_SMD:C_0402_1005Metric",
                "Inductor_SMD:L_0402_1005Metric",
                "LED_SMD:LED_0402_1005Metric",
            ],
            "0603": [
                "Resistor_SMD:R_0603_1608Metric",
                "Capacitor_SMD:C_0603_1608Metric",
                "Inductor_SMD:L_0603_1608Metric",
                "LED_SMD:LED_0603_1608Metric",
            ],
            "0805": [
                "Resistor_SMD:R_0805_2012Metric",
                "Capacitor_SMD:C_0805_2012Metric",
                "Inductor_SMD:L_0805_2012Metric",
                "LED_SMD:LED_0805_2012Metric",
            ],
            "1206": [
                "Resistor_SMD:R_1206_3216Metric",
                "Capacitor_SMD:C_1206_3216Metric",
                "Inductor_SMD:L_1206_3216Metric",
            ],
            "1210": [
                "Resistor_SMD:R_1210_3225Metric",
                "Capacitor_SMD:C_1210_3225Metric",
            ],
            "1812": [
                "Resistor_SMD:R_1812_4532Metric",
                "Capacitor_SMD:C_1812_4532Metric",
            ],
            "2010": [
                "Resistor_SMD:R_2010_5025Metric",
            ],
            "2512": [
                "Resistor_SMD:R_2512_6332Metric",
                "Capacitor_SMD:C_2512_6332Metric",
            ],
            # SOT packages
            "SOT-23": [
                "Package_TO_SOT_SMD:SOT-23",
                "Package_TO_SOT_SMD:SOT-23-3",
            ],
            "SOT-23-5": ["Package_TO_SOT_SMD:SOT-23-5"],
            "SOT-23-6": ["Package_TO_SOT_SMD:SOT-23-6"],
            "SOT-323": ["Package_TO_SOT_SMD:SOT-323_SC-70"],
            "SC-70": ["Package_TO_SOT_SMD:SOT-323_SC-70"],
            "SC-70-5": ["Package_TO_SOT_SMD:SOT-353_SC-70-5"],
            "SC-70-6": ["Package_TO_SOT_SMD:SOT-363_SC-70-6"],
            "SOT-89": ["Package_TO_SOT_SMD:SOT-89-3"],
            "SOT-223": ["Package_TO_SOT_SMD:SOT-223-3_TabPin2"],
            "SOT-363": ["Package_TO_SOT_SMD:SOT-363_SC-70-6"],
            "SOT-523": ["Package_TO_SOT_SMD:SOT-523"],
            "SOT-563": ["Package_TO_SOT_SMD:SOT-563"],
            "SOT-666": ["Package_TO_SOT_SMD:SOT-666"],
            "SOT-143": ["Package_TO_SOT_SMD:SOT-143"],
            # SOIC / SOP
            "SOIC-8": ["Package_SO:SOIC-8_3.9x4.9mm_P1.27mm"],
            "SOP-8": ["Package_SO:SOIC-8_3.9x4.9mm_P1.27mm"],
            "SOIC-14": ["Package_SO:SOIC-14_3.9x8.7mm_P1.27mm"],
            "SOIC-16": ["Package_SO:SOIC-16_3.9x9.9mm_P1.27mm"],
            "SOIC-16W": ["Package_SO:SOIC-16W_7.5x10.3mm_P1.27mm"],
            "SOIC-18": ["Package_SO:SOIC-18W_7.5x11.6mm_P1.27mm"],
            "SOIC-20": ["Package_SO:SOIC-20W_7.5x12.8mm_P1.27mm"],
            "SOIC-24": ["Package_SO:SOIC-24W_7.5x15.4mm_P1.27mm"],
            "SOIC-28": ["Package_SO:SOIC-28W_7.5x18.7mm_P1.27mm"],
            # SSOP / TSSOP / MSOP
            "SSOP-8": ["Package_SO:SSOP-8_3.95x5.21mm_P1.27mm"],
            "SSOP-16": ["Package_SO:SSOP-16_5.3x6.2mm_P0.65mm"],
            "SSOP-20": ["Package_SO:SSOP-20_5.3x7.2mm_P0.65mm"],
            "SSOP-24": ["Package_SO:SSOP-24_5.3x8.2mm_P0.65mm"],
            "SSOP-28": ["Package_SO:SSOP-28_5.3x10.2mm_P0.65mm"],
            "TSSOP-8": ["Package_SO:TSSOP-8_3x3mm_P0.65mm"],
            "TSSOP-14": ["Package_SO:TSSOP-14_4.4x5mm_P0.65mm"],
            "TSSOP-16": ["Package_SO:TSSOP-16_4.4x5mm_P0.65mm"],
            "TSSOP-20": ["Package_SO:TSSOP-20_4.4x6.5mm_P0.65mm"],
            "TSSOP-24": ["Package_SO:TSSOP-24_4.4x7.8mm_P0.65mm"],
            "TSSOP-28": ["Package_SO:TSSOP-28_4.4x9.7mm_P0.65mm"],
            "MSOP-8": ["Package_SO:MSOP-8_3x3mm_P0.65mm"],
            "MSOP-10": ["Package_SO:MSOP-10_3x3mm_P0.5mm"],
            # QFN / DFN
            "QFN-8": ["Package_DFN_QFN:QFN-8-1EP_2x2mm_P0.5mm_EP0.9x0.9mm"],
            "QFN-12": ["Package_DFN_QFN:QFN-12-1EP_3x3mm_P0.5mm_EP1.65x1.65mm"],
            "QFN-16": ["Package_DFN_QFN:QFN-16-1EP_3x3mm_P0.5mm_EP1.45x1.45mm"],
            "QFN-20": ["Package_DFN_QFN:QFN-20-1EP_4x4mm_P0.5mm_EP2.5x2.5mm"],
            "QFN-24": ["Package_DFN_QFN:QFN-24-1EP_4x4mm_P0.5mm_EP2.45x2.45mm"],
            "QFN-28": ["Package_DFN_QFN:QFN-28-1EP_5x5mm_P0.5mm_EP3.35x3.35mm"],
            "QFN-32": ["Package_DFN_QFN:QFN-32-1EP_5x5mm_P0.5mm_EP3.45x3.45mm"],
            "QFN-36": ["Package_DFN_QFN:QFN-36-1EP_6x6mm_P0.5mm_EP4.1x4.1mm"],
            "QFN-40": ["Package_DFN_QFN:QFN-40-1EP_6x6mm_P0.5mm_EP4.1x4.1mm"],
            "QFN-44": ["Package_DFN_QFN:QFN-44-1EP_7x7mm_P0.5mm_EP5.15x5.15mm"],
            "QFN-48": ["Package_DFN_QFN:QFN-48-1EP_7x7mm_P0.5mm_EP5.15x5.15mm"],
            "QFN-56": ["Package_DFN_QFN:QFN-56-1EP_7x7mm_P0.4mm_EP5.6x5.6mm"],
            "QFN-64": ["Package_DFN_QFN:QFN-64-1EP_9x9mm_P0.5mm_EP5.4x5.4mm"],
            "DFN-6": ["Package_DFN_QFN:DFN-6-1EP_2x2mm_P0.65mm_EP1x1.6mm"],
            "DFN-8": ["Package_DFN_QFN:DFN-8-1EP_3x2mm_P0.5mm_EP1.36x1.46mm"],
            "DFN-10": ["Package_DFN_QFN:DFN-10-1EP_3x3mm_P0.5mm_EP1.55x2.48mm"],
            "DFN-12": ["Package_DFN_QFN:DFN-12-1EP_3x4mm_P0.5mm_EP1.7x3.3mm"],
            # QFP / LQFP / TQFP
            "LQFP-32": ["Package_QFP:LQFP-32_7x7mm_P0.8mm"],
            "LQFP-44": ["Package_QFP:LQFP-44_10x10mm_P0.8mm"],
            "LQFP-48": ["Package_QFP:LQFP-48_7x7mm_P0.5mm"],
            "LQFP-64": ["Package_QFP:LQFP-64_10x10mm_P0.5mm"],
            "LQFP-80": ["Package_QFP:LQFP-80_12x12mm_P0.5mm"],
            "LQFP-100": ["Package_QFP:LQFP-100_14x14mm_P0.5mm"],
            "LQFP-128": ["Package_QFP:LQFP-128_14x14mm_P0.4mm"],
            "LQFP-144": ["Package_QFP:LQFP-144_20x20mm_P0.5mm"],
            "LQFP-176": ["Package_QFP:LQFP-176_24x24mm_P0.5mm"],
            "LQFP-208": ["Package_QFP:LQFP-208_28x28mm_P0.5mm"],
            "TQFP-32": ["Package_QFP:TQFP-32_7x7mm_P0.8mm"],
            "TQFP-44": ["Package_QFP:TQFP-44_10x10mm_P0.8mm"],
            "TQFP-48": ["Package_QFP:TQFP-48_7x7mm_P0.5mm"],
            "TQFP-64": ["Package_QFP:TQFP-64_10x10mm_P0.5mm"],
            "TQFP-100": ["Package_QFP:TQFP-100_14x14mm_P0.5mm"],
            # BGA
            "BGA-48": ["Package_BGA:BGA-48_6x8_5.0x7.0mm_P0.8mm"],
            "BGA-100": ["Package_BGA:BGA-100_10x10_9.0x9.0mm_P0.8mm"],
            "BGA-144": ["Package_BGA:BGA-144_12x12_10.0x10.0mm_P0.8mm"],
            "BGA-169": ["Package_BGA:BGA-169_13x13_11.0x11.0mm_P0.8mm"],
            "BGA-196": ["Package_BGA:BGA-196_14x14_12.0x12.0mm_P0.8mm"],
            "BGA-256": ["Package_BGA:BGA-256_16x16_14.0x14.0mm_P0.8mm"],
            # TO packages (through-hole and SMD)
            "TO-92": ["Package_TO_SOT_THT:TO-92_Inline"],
            "TO-220": ["Package_TO_SOT_THT:TO-220-3_Vertical"],
            "TO-220-3": ["Package_TO_SOT_THT:TO-220-3_Vertical"],
            "TO-220F": ["Package_TO_SOT_THT:TO-220F-3_Vertical"],
            "TO-252": ["Package_TO_SOT_SMD:TO-252-2"],
            "DPAK": ["Package_TO_SOT_SMD:TO-252-2"],
            "TO-263": ["Package_TO_SOT_SMD:TO-263-3_TabPin2"],
            "D2PAK": ["Package_TO_SOT_SMD:TO-263-3_TabPin2"],
            "D-PAK": ["Package_TO_SOT_SMD:TO-252-2"],
            "TO-247": ["Package_TO_SOT_THT:TO-247-3_Vertical"],
            "SOD-123": ["Diode_SMD:D_SOD-123"],
            "SOD-323": ["Diode_SMD:D_SOD-323"],
            "SOD-523": ["Diode_SMD:D_SOD-523"],
            "SOD-123F": ["Diode_SMD:D_SOD-123F"],
            "SOD-128": ["Diode_SMD:D_SOD-128"],
            "SMA": ["Diode_SMD:D_SMA"],
            "SMB": ["Diode_SMD:D_SMB"],
            "SMC": ["Diode_SMD:D_SMC"],
            # Connectors (common JLCPCB connectors)
            "USB-C": ["Connector_USB:USB_C_Receptacle_XKB_U262-16XN-4BVC11"],
            "USB-A": ["Connector_USB:USB_A_Stewart_SS-52100-001"],
            "USB-MICRO": ["Connector_USB:USB_Micro-B_Molex-105017-0001"],
            "USB-MINI": ["Connector_USB:USB_Mini-B_Lumberg_2486_01_Horizontal"],
            # Crystal / Oscillator packages
            "HC49": ["Crystal:Crystal_HC49-4H_Vertical"],
            "2012": ["Crystal:Crystal_SMD_2012-2Pin_2.0x1.2mm"],
            "3215": ["Crystal:Crystal_SMD_3215-2Pin_3.2x1.5mm"],
            "5032": ["Crystal:Crystal_SMD_5032-2Pin_5.0x3.2mm"],
            "7050": ["Crystal:Crystal_SMD_7050-4Pin_7.0x5.0mm"],
            # Electrolytic capacitors
            "CAP-D4": ["Capacitor_SMD:CP_Elec_4x5.4"],
            "CAP-D5": ["Capacitor_SMD:CP_Elec_5x5.4"],
            "CAP-D6.3": ["Capacitor_SMD:CP_Elec_6.3x5.4"],
            "CAP-D8": ["Capacitor_SMD:CP_Elec_8x10.5"],
            "CAP-D10": ["Capacitor_SMD:CP_Elec_10x10.5"],
        }

        # Normalize package name
        package_normalized = package.strip().upper()

        for key, footprints in mappings.items():
            if key.upper() in package_normalized:
                return footprints

        return []

    def suggest_alternatives(self, lcsc_number: str, limit: int = 5) -> List[Dict]:
        """
        Find alternative parts similar to the given LCSC number

        Prioritizes: cheaper price, higher stock, Basic library type

        Args:
            lcsc_number: Reference LCSC part number
            limit: Maximum alternatives to return

        Returns:
            List of alternative parts
        """
        part = self.get_part_info(lcsc_number)
        if not part:
            return []

        # Search for parts in same category with same package
        alternatives = self.search_parts(
            category=part['subcategory'],
            package=part['package'],
            in_stock=True,
            limit=limit * 3
        )

        # Filter out the original part
        alternatives = [p for p in alternatives if p['lcsc'] != lcsc_number]

        # Sort by: Basic first, then by price, then by stock
        def sort_key(p):
            is_basic = 1 if p.get('library_type') == 'Basic' else 0
            try:
                prices = json.loads(p.get('price_json', '[]'))
                price = float(prices[0].get('price', 999)) if prices else 999
            except (json.JSONDecodeError, TypeError, ValueError, IndexError, KeyError):
                price = 999
            stock = p.get('stock', 0)

            return (-is_basic, price, -stock)

        alternatives.sort(key=sort_key)

        return alternatives[:limit]

    def close(self):
        """Close database connection"""
        if self.conn:
            self.conn.close()


    # ── JLCPCB Rotation Corrections ───────────────────────────────────
    # KiCad and JLCPCB use different pin-1 conventions for some packages.
    # These corrections are applied to the position (CPL) file before upload.

    ROTATION_CORRECTIONS = {
        # SOT packages
        "SOT-23": -180,
        "SOT-23-3": -180,
        "SOT-23-5": -180,
        "SOT-23-6": -180,
        "SOT-323": -180,
        "SOT-363": -180,
        "SOT-89": -180,
        "SOT-89-3": -180,
        "SOT-223": -180,
        "SOT-223-3": -180,
        # SOIC
        "SOIC-8": -90,
        "SOIC-14": -90,
        "SOIC-16": -90,
        "SOIC-18": -90,
        "SOIC-20": -90,
        "SOIC-24": -90,
        "SOIC-28": -90,
        # SSOP / TSSOP / MSOP
        "SSOP-8": -90,
        "SSOP-14": -90,
        "SSOP-16": -90,
        "SSOP-20": -90,
        "SSOP-24": -90,
        "SSOP-28": -90,
        "TSSOP-8": -90,
        "TSSOP-14": -90,
        "TSSOP-16": -90,
        "TSSOP-20": -90,
        "TSSOP-24": -90,
        "TSSOP-28": -90,
        "MSOP-8": -90,
        "MSOP-10": -90,
        # QFN
        "QFN-8": -90,
        "QFN-12": -90,
        "QFN-16": -90,
        "QFN-20": -90,
        "QFN-24": -90,
        "QFN-28": -90,
        "QFN-32": -90,
        "QFN-40": -90,
        "QFN-44": -90,
        "QFN-48": -90,
        "QFN-56": -90,
        "QFN-64": -90,
        "DFN-6": -90,
        "DFN-8": -90,
        # QFP / LQFP / TQFP
        "LQFP-32": -90,
        "LQFP-44": -90,
        "LQFP-48": -90,
        "LQFP-64": -90,
        "LQFP-80": -90,
        "LQFP-100": -90,
        "LQFP-128": -90,
        "LQFP-144": -90,
        "LQFP-176": -90,
        "LQFP-208": -90,
        "TQFP-32": -90,
        "TQFP-44": -90,
        "TQFP-48": -90,
        "TQFP-64": -90,
        "TQFP-100": -90,
        # Diodes
        "SOD-123": -180,
        "SOD-323": -180,
        "SOD-523": -180,
        "SMA": -180,
        "SMB": -180,
        "SMC": -180,
        # TO packages
        "TO-252-2": -180,
        "TO-263-2": -180,
        # USB connectors
        "USB-C-SMD": 0,
        "USB-A-TH": 0,
        "USB-Micro-B": 0,
    }

    def get_rotation_correction(self, package: str) -> Dict:
        """
        Get JLCPCB rotation correction for a KiCad footprint.

        Args:
            package: Package name (e.g., "SOT-23", "SOIC-8", "QFN-32")

        Returns:
            Correction info including angle offset to apply
        """
        # Try exact match first
        correction = self.ROTATION_CORRECTIONS.get(package, None)

        # Try case-insensitive
        if correction is None:
            for key, val in self.ROTATION_CORRECTIONS.items():
                if key.upper() == package.upper():
                    correction = val
                    break

        # Try partial match (e.g., "QFN-32-EP" matches "QFN-32")
        if correction is None:
            for key, val in self.ROTATION_CORRECTIONS.items():
                if package.upper().startswith(key.upper()):
                    correction = val
                    break

        if correction is not None:
            return {
                "success": True,
                "package": package,
                "rotation_correction_deg": correction,
                "message": f"Apply {correction}° rotation correction for JLCPCB CPL",
            }

        return {
            "success": True,
            "package": package,
            "rotation_correction_deg": 0,
            "message": "No correction needed (or unknown package)",
        }

    def generate_corrected_cpl(self, board_path: Optional[str] = None) -> Dict:
        """
        Generate a JLCPCB-corrected Component Placement List (CPL) file.

        Reads the board, applies rotation corrections, and outputs a CSV
        ready for JLCPCB upload.

        Args:
            board_path: Path to .kicad_pcb file (uses loaded board if None)

        Returns:
            Dict with file path and correction summary
        """
        try:
            import pcbnew

            if board_path:
                board = pcbnew.LoadBoard(board_path)
            else:
                board = pcbnew.GetBoard()

            if not board:
                return {"success": False, "error": "No board available"}

            import csv
            import tempfile

            output_path = str(Path(board.GetFileName()).with_suffix('.cpl.csv'))

            rows = []
            corrections_applied = 0

            for fp in board.GetFootprints():
                if fp.GetLayer() != pcbnew.F_Cu and fp.GetLayer() != pcbnew.B_Cu:
                    continue

                ref = fp.GetReference()
                value = fp.GetValue()
                pos = fp.GetPosition()
                rotation = fp.GetOrientationDegrees()
                layer = "top" if fp.GetLayer() == pcbnew.F_Cu else "bottom"

                # Determine package for correction lookup
                fp_name = str(fp.GetFPID().GetUniStringLibItemName())
                package = self._extract_package_name(fp_name)

                # Apply correction
                correction = self.ROTATION_CORRECTIONS.get(package, 0)
                if correction == 0:
                    for key, val in self.ROTATION_CORRECTIONS.items():
                        if package.upper().startswith(key.upper()):
                            correction = val
                            break

                corrected_rotation = (rotation + correction) % 360
                if correction != 0:
                    corrections_applied += 1

                rows.append({
                    "Designator": ref,
                    "Val": value,
                    "Package": fp_name,
                    "Mid X": f"{pcbnew.ToMM(pos.x):.4f}mm",
                    "Mid Y": f"{-pcbnew.ToMM(pos.y):.4f}mm",  # JLCPCB Y is inverted
                    "Rotation": f"{corrected_rotation:.1f}",
                    "Layer": layer,
                })

            with open(output_path, 'w', newline='') as f:
                writer = csv.DictWriter(f, fieldnames=[
                    "Designator", "Val", "Package", "Mid X", "Mid Y", "Rotation", "Layer"
                ])
                writer.writeheader()
                writer.writerows(rows)

            return {
                "success": True,
                "output_path": output_path,
                "total_components": len(rows),
                "corrections_applied": corrections_applied,
                "message": f"Generated CPL with {corrections_applied} rotation corrections: {output_path}",
            }

        except Exception as e:
            logger.error(f"Generate corrected CPL failed: {e}")
            return {"success": False, "error": str(e)}

    def parametric_search(self, **kwargs) -> Dict:
        """Search parts by parsed parametric values (value + unit + package)."""
        import re

        query = kwargs.get("query", "")
        value = kwargs.get("value")
        unit = kwargs.get("unit")
        package = kwargs.get("package")
        tolerance = kwargs.get("tolerance")
        voltage_rating = kwargs.get("voltage_rating")
        library_type = kwargs.get("library_type", "All")
        sort_by = kwargs.get("sort_by", "price")
        limit = kwargs.get("limit", 20)

        if query and not value:
            value, unit, package = self._parse_parametric_query(query)

        if not value:
            return {
                "success": False,
                "error": "Could not parse parametric value. Use format like '100nF 0402' or '10k 0805'."
            }

        search_terms = []
        if value and unit:
            search_terms.append(f"{value}{unit}")
            normalized = self._normalize_value(value, unit)
            if normalized != f"{value}{unit}":
                search_terms.append(normalized)

        combined_query = " ".join(search_terms) if search_terms else str(value)
        results = self.search_parts(
            query=combined_query,
            package=package,
            library_type=library_type if library_type != "All" else None,
            limit=limit * 3,
        )

        if voltage_rating:
            vr = str(voltage_rating).upper()
            results = [p for p in results if vr in (p.get("description", "").upper())]

        if tolerance:
            tol_str = str(tolerance).replace("%", "")
            results = [p for p in results if tol_str in (p.get("description", "") or "")]

        if sort_by == "price":
            results.sort(key=lambda p: self._get_unit_price(p))
        elif sort_by == "stock":
            results.sort(key=lambda p: -(p.get("stock", 0) or 0))

        results = results[:limit]

        return {
            "success": True,
            "parsed": {"value": value, "unit": unit, "package": package},
            "count": len(results),
            "parts": results,
        }

    def match_bom(self, **kwargs) -> Dict:
        """Match a BOM (list of components) to JLCPCB parts."""
        components = kwargs.get("components", [])
        prefer_basic = kwargs.get("prefer_basic", True)
        results = []

        for comp in components:
            ref = comp.get("reference", "")
            value = comp.get("value", "")
            footprint = comp.get("footprint", "")
            lcsc = comp.get("lcsc", "")

            match_result = {"reference": ref, "value": value, "footprint": footprint}

            if lcsc:
                part = self.get_part_info(lcsc)
                if part:
                    match_result["matched_part"] = part
                    match_result["match_method"] = "lcsc_number"
                    match_result["matched"] = True
                    results.append(match_result)
                    continue

            package = self._extract_package_name(footprint.split(":")[-1]) if footprint else None
            search_q = value
            if package:
                search_q = f"{value} {package}"

            candidates = self.search_parts(query=search_q, limit=10)

            if prefer_basic:
                basic = [p for p in candidates if p.get("library_type") == "Basic"]
                if basic:
                    candidates = basic + [p for p in candidates if p.get("library_type") != "Basic"]

            if candidates:
                match_result["matched_part"] = candidates[0]
                match_result["alternatives"] = candidates[1:5]
                match_result["match_method"] = "search"
                match_result["matched"] = True
            else:
                match_result["matched"] = False
                match_result["match_method"] = "none"

            results.append(match_result)

        matched_count = sum(1 for r in results if r.get("matched"))
        basic_count = sum(
            1 for r in results
            if r.get("matched") and r.get("matched_part", {}).get("library_type") == "Basic"
        )

        return {
            "success": True,
            "total_components": len(components),
            "matched": matched_count,
            "unmatched": len(components) - matched_count,
            "basic_parts": basic_count,
            "extended_parts": matched_count - basic_count,
            "results": results,
        }

    def cost_estimate(self, **kwargs) -> Dict:
        """Estimate PCB assembly cost based on matched BOM."""
        components = kwargs.get("components", [])
        quantity = kwargs.get("quantity", 5)

        bom_result = self.match_bom(components=components)
        if not bom_result.get("success"):
            return bom_result

        total_part_cost = 0.0
        extended_setup_fee = 0.0
        part_costs = []

        for r in bom_result["results"]:
            if not r.get("matched"):
                continue
            part = r["matched_part"]
            unit_price = self._get_unit_price(part, quantity)
            line_cost = unit_price * quantity

            part_entry = {
                "reference": r["reference"],
                "lcsc": part.get("lcsc", ""),
                "unit_price": round(unit_price, 4),
                "line_cost": round(line_cost, 4),
                "library_type": part.get("library_type", ""),
            }

            if part.get("library_type") == "Extended":
                extended_setup_fee += 3.0
                part_entry["setup_fee"] = 3.0

            total_part_cost += line_cost
            part_costs.append(part_entry)

        return {
            "success": True,
            "quantity": quantity,
            "unique_parts": len(part_costs),
            "total_part_cost": round(total_part_cost, 2),
            "extended_setup_fees": round(extended_setup_fee, 2),
            "estimated_total": round(total_part_cost + extended_setup_fee, 2),
            "basic_parts": bom_result["basic_parts"],
            "extended_parts": bom_result["extended_parts"],
            "unmatched": bom_result["unmatched"],
            "part_costs": part_costs,
        }

    def _parse_parametric_query(self, query: str):
        """Parse a human query like '100nF 0402' into (value, unit, package)."""
        import re

        query = query.strip()
        value, unit, package = None, None, None

        pkg_match = re.search(r'\b(0201|0402|0603|0805|1206|1210|1812|2010|2512)\b', query)
        if pkg_match:
            package = pkg_match.group(1)
            query = query[:pkg_match.start()] + query[pkg_match.end():]

        pkg_match2 = re.search(r'\b(SOT-\d+|SOIC-\d+|QFN-\d+|LQFP-\d+|TSSOP-\d+|SMA|SMB|SMC)\b',
                               query, re.IGNORECASE)
        if pkg_match2:
            package = pkg_match2.group(1)
            query = query[:pkg_match2.start()] + query[pkg_match2.end():]

        val_match = re.search(
            r'(\d+(?:\.\d+)?)\s*(pF|nF|uF|µF|mF|F|pH|nH|uH|µH|mH|H|'
            r'mΩ|Ω|ohm|kΩ|kohm|MΩ|Mohm|k|M|R|V|A|mA|mV|W|mW)\b',
            query, re.IGNORECASE
        )
        if val_match:
            value = val_match.group(1)
            unit = val_match.group(2)
            unit = unit.replace("µ", "u").replace("Ω", "ohm")
            if unit.lower() in ("k", "kohm"):
                unit = "kohm"
            elif unit.lower() in ("m", "mohm") and float(value) > 0.1:
                unit = "Mohm"
        else:
            num_match = re.search(r'(\d+(?:\.\d+)?)', query)
            if num_match:
                value = num_match.group(1)

        return value, unit, package

    def _normalize_value(self, value: str, unit: str) -> str:
        """Normalize a value+unit to standard form."""
        UNIT_MAP = {
            "kohm": "kOhms", "mohm": "MOhms", "ohm": "Ohms", "r": "Ohms",
            "pf": "pF", "nf": "nF", "uf": "uF", "mf": "mF", "f": "F",
            "ph": "pH", "nh": "nH", "uh": "uH", "mh": "mH", "h": "H",
        }
        normalized_unit = UNIT_MAP.get(unit.lower(), unit)
        return f"{value}{normalized_unit}"

    def _get_unit_price(self, part: Dict, quantity: int = 1) -> float:
        """Extract unit price from a part's price breaks."""
        try:
            price_str = part.get("price", "[]")
            if isinstance(price_str, str):
                prices = json.loads(price_str)
            else:
                prices = price_str or []

            if not prices:
                return 999.0

            best_price = prices[0].get("price", 999.0)
            for pb in prices:
                if pb.get("qty", 0) <= quantity:
                    best_price = pb.get("price", best_price)
            return float(best_price)
        except (json.JSONDecodeError, TypeError, ValueError, KeyError):
            return 999.0

    def _extract_package_name(self, footprint_name: str) -> str:
        """Extract package name from a KiCad footprint name."""
        # e.g., "R_0402_1005Metric" -> "0402"
        # e.g., "SOT-23-3" -> "SOT-23-3"
        # e.g., "QFN-32-1EP_5x5mm_P0.5mm" -> "QFN-32"
        parts = footprint_name.split("_")
        if len(parts) >= 2:
            # Check if second part is a metric size
            if parts[1] and parts[1][0].isdigit() and "Metric" in footprint_name:
                return parts[1].split("Metric")[0]
        # Try the first part as-is for packages like SOT-23, QFN-32
        base = parts[0] if parts else footprint_name
        # Strip trailing details after the pin count
        for suffix in ["_EP", "_Pad", "_P0", "_HandSoldering"]:
            if suffix in base:
                base = base[:base.index(suffix)]
        return base


if __name__ == '__main__':
    # Test the parts manager
    logging.basicConfig(level=logging.INFO)

    manager = JLCPCBPartsManager()

    # Get stats
    stats = manager.get_database_stats()
    print(f"\nDatabase Statistics:")
    print(f"  Total parts: {stats['total_parts']}")
    print(f"  Basic parts: {stats['basic_parts']}")
    print(f"  Extended parts: {stats['extended_parts']}")
    print(f"  In stock: {stats['in_stock']}")
    print(f"  Database: {stats['db_path']}")

    if stats['total_parts'] > 0:
        print("\nSearching for '10k resistor'...")
        results = manager.search_parts(query="10k resistor", limit=5)
        for part in results:
            print(f"  {part['lcsc']}: {part['mfr_part']} - {part['description']} ({part['library_type']})")
