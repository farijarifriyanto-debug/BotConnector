# OLAHDOKUMEN FREE FEATURES V2 - Document Extraction Engine
# Backend implementation for structured data extraction from documents

import os
import json
import csv
import re
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass
from pathlib import Path

@dataclass
class ExtractionResult:
    """Result of extracting structured data from a document."""
    fields: Dict[str, Any]
    tables: List[List[Any]]
    extracted_data: Dict[str, Any]
    invoices: List[Dict[str, Any]]
    contracts: List[Dict[str, Any]]
    budgets: List[Dict[str, Any]]
    custom_fields: Dict[str, Any]
    metadata: Dict[str, Any]

class DocumentExtractor:
    """Core class for document extraction functionality."""

    def __init__(self):
        pass

    def extract_from_document(self, document: Dict[str, Any], custom_fields: Optional[List[str]] = None) -> ExtractionResult:
        """Extract structured data from a document.

        Args:
            document: Document dict with 'content' field
            custom_fields: List of custom fields to extract (optional)

        Returns:
            ExtractionResult object with extracted structured data
        """
        content = document.get('content', '')

        if not content:
            return ExtractionResult(
                fields={},
                tables=[],
                extracted_data={},
                invoices=[],
                contracts=[],
                budgets=[],
                custom_fields={},
                metadata={'empty_content': True}
            )

        # Extract general fields
        fields = self._extract_general_fields(content)

        # Extract tables
        tables = self._extract_tables(content)

        # Extract structured data based on content patterns
        extracted_data = self._extract_structured_data(content)

        # Extract invoices
        invoices = self._extract_invoices(content)

        # Extract contracts
        contracts = self._extract_contracts(content)

        # Extract budgets
        budgets = self._extract_budgets(content)

        # Extract custom fields
        custom_fields_result = self._extract_custom_fields(content, custom_fields or [])

        # Extract metadata
        metadata = self._extract_metadata(document)

        return ExtractionResult(
            fields=fields,
            tables=tables,
            extracted_data=extracted_data,
            invoices=invoices,
            contracts=contracts,
            budgets=budgets,
            custom_fields=custom_fields_result,
            metadata=metadata
        )

    def _extract_general_fields(self, content: str) -> Dict[str, Any]:
        """Extract general fields from content."""
        fields = {}

        # Extract money values
        money_pattern = r'Rp\d+(?:,\d+)*\.?\d*'
        money_matches = re.findall(money_pattern, content)
        if money_matches:
            fields['money_values'] = money_matches

        # Extract numbers
        number_pattern = r'\d+(?:\.\d+)?'
        number_matches = re.findall(number_pattern, content)
        if number_matches:
            fields['numbers'] = [float(x) if '.' in x else int(x) for x in number_matches]

        # Extract percentages
        percent_pattern = r'\d+%'
        percent_matches = re.findall(percent_pattern, content)
        if percent_matches:
            fields['percentages'] = [x.replace('%', '') for x in percent_matches]

        # Extract dates
        date_pattern = r'\d{1,2}\s+(?:Jan|Feb|Mar|Apr|Mei|Jun|Jul|Aug|Sep|Oct|Nov|Des)\s+\d{4}'
        date_matches = re.findall(date_pattern, content, re.IGNORECASE)
        if date_matches:
            fields['dates'] = date_matches

        # Extract names (simple heuristic: capitalized words after certain patterns)
        name_pattern = r'(?:nama|vendor|client|perusahaan)\s*:?\s*([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)'
        name_matches = re.findall(name_pattern, content, re.IGNORECASE)
        if name_matches:
            fields['names'] = name_matches

        # Extract contract numbers
        contract_pattern = r'(?:nomor|no\.)\s*kontrak\s*:?\s*([A-Za-z0-9\-\/]+)'
        contract_matches = re.findall(contract_pattern, content, re.IGNORECASE)
        if contract_matches:
            fields['contract_numbers'] = contract_matches

        # Extract invoice numbers
        invoice_pattern = r'(?:invoice|faktur)\s*(?:no|nomor)\s*:?\s*([A-Za-z0-9\-]+)'
        invoice_matches = re.findall(invoice_pattern, content, re.IGNORECASE)
        if invoice_matches:
            fields['invoice_numbers'] = invoice_matches

        return fields

    def _extract_tables(self, content: str) -> List[List[Any]]:
        """Extract table-like data from content."""
        tables = []

        # Look for table patterns (lines with multiple columns)
        lines = content.split('\n')
        potential_tables = []

        for line in lines:
            if re.search(r'\d+.*\d+.*\d+', line):  # Line with multiple numbers
                # Try to parse as table row
                cells = self._parse_table_line(line)
                if len(cells) > 1:
                    potential_tables.append(cells)

        # Group related rows into tables
        if potential_tables:
            tables.append(potential_tables)

        return tables

    def _parse_table_line(self, line: str) -> List[Any]:
        """Parse a line into table cells."""
        # Simple column splitting by multiple spaces or tabs
        cells = re.split(r'\s{2,}|\t', line.strip())

        # Clean and validate cells
        cleaned_cells = []
        for cell in cells:
            cell = cell.strip()
            if cell:
                # Try to convert to appropriate type
                if re.match(r'^\d+(?:,\d+)*\.?\d*$', cell.replace(',', '')):
                    # Money or number
                    try:
                        if 'Rp' in cell:
                            cleaned_cells.append(cell)
                        else:
                            num = float(cell.replace(',', ''))
                        cleaned_cells.append(cell)
                    except ValueError:
                        cleaned_cells.append(cell)
                else:
                    cleaned_cells.append(cell)

        return cleaned_cells

    def _extract_structured_data(self, content: str) -> Dict[str, Any]:
        """Extract structured data based on content patterns."""
        data = {}

        # Check for invoice-like data
        if self._contains_invoice_pattern(content):
            data['type'] = 'invoice'
            data['invoice_details'] = self._extract_invoice_details(content)

        # Check for contract-like data
        elif self._contains_contract_pattern(content):
            data['type'] = 'contract'
            data['contract_details'] = self._extract_contract_details(content)

        # Check for budget-like data
        elif self._contains_budget_pattern(content):
            data['type'] = 'budget'
            data['budget_details'] = self._extract_budget_details(content)

        else:
            data['type'] = 'general'
            data['general_content'] = content

        return data

    def _contains_invoice_pattern(self, content: str) -> bool:
        """Check if content contains invoice-like patterns."""
        invoice_keywords = ['invoice', 'faktur', 'tagihan', 'pembayaran', 'total', 'subtotal', 'ongkos kirim']
        for keyword in invoice_keywords:
            if keyword.lower() in content.lower():
                return True
        return False

    def _contains_contract_pattern(self, content: str) -> bool:
        """Check if content contains contract-like patterns."""
        contract_keywords = ['kontrak', 'perjanjian', 'klausul', 'pihak', 'berdasarkan', 'nilai kontrak', 'pelaksanaan']
        for keyword in contract_keywords:
            if keyword.lower() in content.lower():
                return True
        return False

    def _contains_budget_pattern(self, content: str) -> bool:
        """Check if content contains budget-like patterns."""
        budget_keywords = ['anggaran', 'budget', 'RAB', 'biaya', ' RAB ', 'pengeluaran']
        for keyword in budget_keywords:
            if keyword.lower() in content.lower():
                return True
        return False

    def _extract_invoice_details(self, content: str) -> Dict[str, Any]:
        """Extract invoice details from content."""
        details = {}

        # Extract invoice number
        invoice_pattern = r'(?:invoice|faktur)\s*(?:no|nomor)\s*:?\s*([A-Za-z0-9\-]+)'
        invoice_matches = re.findall(invoice_pattern, content, re.IGNORECASE)
        if invoice_matches:
            details['invoice_number'] = invoice_matches[0]

        # Extract dates
        date_pattern = r'\d{1,2}\s+(?:Jan|Feb|Mar|Apr|Mei|Jun|Jul|Aug|Sep|Oct|Nov|Des)\s+\d{4}'
        date_matches = re.findall(date_pattern, content, re.IGNORECASE)
        if date_matches:
            details['dates'] = date_matches

        # Extract money values
        money_pattern = r'Rp\d+(?:,\d+)*\.?\d*'
        money_matches = re.findall(money_pattern, content)
        if money_matches:
            details['amounts'] = money_matches

        return details

    def _extract_contract_details(self, content: str) -> Dict[str, Any]:
        """Extract contract details from content."""
        details = {}

        # Extract contract number
        contract_pattern = r'(?:nomor|no\.)\s*kontrak\s*:?\s*([A-Za-z0-9\-\/]+)'
        contract_matches = re.findall(contract_pattern, content, re.IGNORECASE)
        if contract_matches:
            details['contract_number'] = contract_matches[0]

        # Extract parties
        party_pattern = r'(?:pihak\s+(?:ke|di)\s+\d+)\s*:?\s*([A-Z][a-zA-Z\s\.,]+)'
        party_matches = re.findall(party_pattern, content, re.IGNORECASE)
        if party_matches:
            details['parties'] = party_matches

        # Extract dates
        date_pattern = r'\d{1,2}\s+(?:Jan|Feb|Mar|Apr|Mei|Jun|Jul|Aug|Sep|Oct|Nov|Des)\s+\d{4}'
        date_matches = re.findall(date_pattern, content, re.IGNORECASE)
        if date_matches:
            details['dates'] = date_matches

        # Extract money values
        money_pattern = r'Rp\d+(?:,\d+)*\.?\d*'
        money_matches = re.findall(money_pattern, content)
        if money_matches:
            details['contract_value'] = money_matches[0] if money_matches else None

        return details

    def _extract_budget_details(self, content: str) -> Dict[str, Any]:
        """Extract budget details from content."""
        details = {}

        # Extract budget categories
        category_pattern = r'([A-Z][a-zA-Z\s]+)\s*:\s*Rp?\d+(?:,\d+)*\.?\d*'
        category_matches = re.findall(category_pattern, content, re.IGNORECASE)
        if category_matches:
            details['categories'] = category_matches

        # Extract budget amounts
        money_pattern = r'([A-Z][a-zA-Z\s]+)\s*:\s*Rp\d+(?:,\d+)*\.?\d*'
        budget_matches = re.findall(money_pattern, content, re.IGNORECASE)
        if budget_matches:
            details['budget_items'] = budget_matches

        return details

    def _extract_invoices(self, content: str) -> List[Dict[str, Any]]:
        """Extract invoice data from content."""
        invoices = []

        # Look for invoice-like patterns
        lines = content.split('\n')

        for line in lines:
            if re.search(r'\d+.*\d+.*\d+', line):  # Contains numbers
                invoice = self._parse_invoice_line(line)
                if invoice:
                    invoices.append(invoice)

        return invoices

    def _extract_contracts(self, content: str) -> List[Dict[str, Any]]:
        """Extract contract data from content."""
        contracts = []

        # Look for contract-like patterns
        lines = content.split('\n')

        for line in lines:
            if self._contains_contract_pattern(line):
                contract = self._parse_contract_line(line)
                if contract:
                    contracts.append(contract)

        return contracts

    def _extract_budgets(self, content: str) -> List[Dict[str, Any]]:
        """Extract budget data from content."""
        budgets = []

        # Look for budget-like patterns
        lines = content.split('\n')

        for line in lines:
            if self._contains_budget_pattern(line):
                budget = self._parse_budget_line(line)
                if budget:
                    budgets.append(budget)

        return budgets

    def _parse_invoice_line(self, line: str) -> Optional[Dict[str, Any]]:
        """Parse a line as an invoice entry."""
        # Extract components
        money_pattern = r'Rp\d+(?:,\d+)*\.?\d*'
        numbers = re.findall(r'\d+', line)

        if money_pattern in line or (numbers and len(numbers) >= 2):
            return {
                'description': line.strip(),
                'amount': re.findall(money_pattern, line)[0] if re.findall(money_pattern, line) else None,
                'quantity': int(numbers[0]) if len(numbers) > 0 else 1,
                'unit_price': int(numbers[1]) if len(numbers) > 1 else None,
                'type': 'invoice'
            }

        return None

    def _parse_contract_line(self, line: str) -> Optional[Dict[str, Any]]:
        """Parse a line as a contract entry."""
        # Extract key contract information
        contract_number_pattern = r'(?:nomor|no\.)\s*kontrak\s*:?\s*([A-Za-z0-9\-\/]+)'
        money_pattern = r'Rp\d+(?:,\d+)*\.?\d*'

        contract_number = re.findall(contract_number_pattern, line, re.IGNORECASE)
        money = re.findall(money_pattern, line)

        if contract_number:
            return {
                'contract_number': contract_number[0],
                'value': money[0] if money else None,
                'description': line.strip(),
                'type': 'contract'
            }

        return None

    def _parse_budget_line(self, line: str) -> Optional[Dict[str, Any]]:
        """Parse a line as a budget entry."""
        # Extract key budget information
        category_pattern = r'([A-Z][a-zA-Z\s]+)\s*:\s*Rp\d+(?:,\d+)*\.?\d*'
        money_pattern = r'Rp\d+(?:,\d+)*\.?\d*'

        categories = re.findall(category_pattern, line, re.IGNORECASE)
        money = re.findall(money_pattern, line)

        if categories or money:
            return {
                'category': categories[0] if categories else 'Unknown',
                'amount': money[0] if money else None,
                'description': line.strip(),
                'type': 'budget'
            }

        return None

    def _extract_custom_fields(self, content: str, custom_fields: List[str]) -> Dict[str, Any]:
        """Extract custom fields from content."""
        custom_result = {}

        for field in custom_fields:
            # Try to extract the field from content
            field_value = self._extract_field_from_content(content, field)
            if field_value:
                custom_result[field] = field_value

        return custom_result

    def _extract_field_from_content(self, content: str, field_name: str) -> Optional[str]:
        """Extract a specific field from content."""
        # Simple pattern matching for common field names
        field_patterns = {
            'nomor kontrak': r'(?:nomor|no\.)\s*kontrak\s*:?\s*([A-Za-z0-9\-\/]+)',
            'vendor': r'(?:vendor|pemasok|supplier)\s*:?\s*([A-Za-zA-Z\s\.,]+?)(?=\s+\d|\s*$|\n)',
            'tanggal': r'\d{1,2}\s+(?:Jan|Feb|Mar|Apr|Mei|Jun|Jul|Aug|Sep|Oct|Nov|Des|Januari|Februari|Maret|April|Mei|Juni|Juli|Agustus|September|Oktober|November|Desember)\s+\d{4}',
            'nilai kontrak': r'Rp\d+(?:,\d{3})*(?:\.\d+)?(?:\.\d{3})*',
            'project': r'(?:proyek|project)\s*:?\s*([A-Za-z0-9\s]+)',
            'lokasi': r'(?:lokasi|location)\s*:?\s*([A-Za-z0-9\s\.,]+)',
            'pekerjaan': r'(?:pekerjaan|work)\s*:?\s*([A-Za-z0-9\s\.,]+)'
        }

        pattern = field_patterns.get(field_name.lower())
        if pattern:
            matches = re.findall(pattern, content, re.IGNORECASE)
            if matches:
                value = matches[0]
                # Clean vendor field - remove date patterns if accidentally included
                if field_name.lower() == 'vendor':
                    value = re.sub(r'\s+\d{1,2}\s+(?:Jan|Feb|Mar|Apr|Mei|Jun|Jul|Aug|Sep|Oct|Nov|Des|Januari|Februari|Maret|April|Mei|Juni|Juli|Agustus|September|Oktober|November|Desember)\s+\d{4}', '', value, flags=re.IGNORECASE)
                    value = value.strip()
                # Clean money values - remove currency symbols for numeric extraction
                elif field_name.lower() == 'nilai kontrak':
                    value = re.sub(r'Rp|,', '', value)
                return value

        return None

    def _extract_metadata(self, document: Dict[str, Any]) -> Dict[str, Any]:
        """Extract metadata from document."""
        metadata = {
            'filename': document.get('filename', ''),
            'format': document.get('format', ''),
            'upload_date': document.get('upload_date', ''),
            'size': document.get('size', 0)
        }

        return metadata

    def export_to_json(self, extraction_result: ExtractionResult) -> str:
        """Export extraction result to JSON string."""
        result_dict = {
            'fields': extraction_result.fields,
            'tables': extraction_result.tables,
            'extracted_data': extraction_result.extracted_data,
            'invoices': extraction_result.invoices,
            'contracts': extraction_result.contracts,
            'budgets': extraction_result.budgets,
            'custom_fields': extraction_result.custom_fields,
            'metadata': extraction_result.metadata
        }
        return json.dumps(result_dict, indent=2, ensure_ascii=False)

    def export_to_csv(self, extraction_result: ExtractionResult, filename: str = "extraction_output.csv") -> str:
        """Export extraction result to CSV file."""
        # For now, export custom fields to CSV format
        if not extraction_result.custom_fields:
            return ""

        # Simple CSV generation
        csv_lines = []
        csv_lines.append(','.join(extraction_result.custom_fields.keys()))

        values_line = []
        for key in extraction_result.custom_fields.keys():
            value = extraction_result.custom_fields[key]
            if isinstance(value, str):
                values_line.append(f'"{value}"')
            else:
                values_line.append(str(value))

        csv_lines.append(','.join(values_line))

        return '\n'.join(csv_lines)

    def export_to_xlsx(self, extraction_result: ExtractionResult, filename: str = "extraction_output.xlsx") -> bytes:
        """Export extraction result to XLSX file (simulated)."""
        # For now, return a simple representation
        data = {
            'filename': filename,
            'format': 'xlsx',
            'content_preview': json.dumps(extraction_result.fields, ensure_ascii=False)
        }
        return json.dumps(data, indent=2, ensure_ascii=False).encode('utf-8')


        if __name__ == "__main__":
            # Test Document Extraction functionality
            print("=" * 60)
            print("Testing Document Extraction Implementation")
            print("=" * 60)

            # Initialize
            extractor = DocumentExtractor()

            # Test documents
            test_documents = [
                {
                    'filename': 'kontrak_A.pdf',
                    'content': 'Kontrak ini menetapkan Nilai kontrak sebesar Rp100.000.000. Pelaksanaan selama 30 hari. Material beli:',
                    'format': 'PDF',
                    'upload_date': '2026-08-27T10:00:00Z',
                    'size': 1024
                },
                {
                    'filename': 'kontrak_B.docx',
                    'content': 'Perjanjian nomor KON-2024-001. Vendor: PT. ABC. Nilai: Rp125.000.000. Berlaku 01 Jan 2024 - 31 Des 2024.',
                    'format': 'DOCX',
                    'upload_date': '2026-08-27T10:05:00Z',
                    'size': 2048
                },
                {
                    'filename': 'invoice.txt',
                    'content': 'INVOICE No: INV-001\nTanggal: 27 Jan 2024\nTotal: Rp50.000.000\nPembayaran: Transfer bank',
                    'format': 'TXT',
                    'upload_date': '2026-08-27T10:10:00Z',
                    'size': 512
                }
            ]

            print("\nTesting document extraction:")

            # Test with default fields
            for i, doc in enumerate(test_documents):
                print(f"\nDocument {i+1}: {doc['filename']}")
                result = extractor.extract_from_document(doc)

                print(f"  Type: {result.extracted_data.get('type', 'unknown')}")
                print(f"  Fields extracted: {len(result.fields)}")
                for key, value in result.fields.items():
                    print(f"    {key}: {value}")

            # Test with custom fields
            custom_fields = ['nomor kontrak', 'vendor', 'tanggal', 'nilai kontrak']
            print(f"\n\nTesting with custom fields: {custom_fields}")

            for i, doc in enumerate(test_documents):
                print(f"\nDocument {i+1} with custom fields:")
                result = extractor.extract_from_document(doc, custom_fields)

                print(f"  Custom fields: {result.custom_fields}")
                print(f"  Metadata: {result.metadata}")

            # Test export functions
            print("\n\nTesting export functions:")

            test_doc = test_documents[0]
            result = extractor.extract_from_document(test_doc)

            # Export to JSON
            json_output = extractor.export_to_json(result)
            print(f"JSON export length: {len(json_output)} chars")

            # Export to CSV
            csv_output = extractor.export_to_csv(result)
            print(f"CSV export length: {len(csv_output)} chars")
            print(f"CSV preview:\n{csv_output}")

            # Export to XLSX
            xlsx_output = extractor.export_to_xlsx(result)
            print(f"XLSX export size: {len(xlsx_output)} bytes")

            print("\n" + "=" * 60)
            print("Document Extraction tests completed successfully!")
            print("=" * 60)
