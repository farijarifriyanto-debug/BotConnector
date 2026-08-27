# OLAHDOKUMEN FREE FEATURES V2 - Multi-Dokumen AI
# Backend implementation for handling multiple documents in one session

import os
import json
import re
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass
from pathlib import Path

@dataclass
class Document:
    """Represents an uploaded document."""
    id: str
    filename: str
    content: str
    format: str
    metadata: Dict[str, Any]

@dataclass
class DocumentChunk:
    """Represents a chunk of document content."""
    text: str
    metadata: Dict[str, Any]

@dataclass
class Citation:
    """Citation for grounded answers."""
    source_document: str
    source_chunk: str
    page: Optional[int] = None

class MultiDocumentAI:
    """Core class for multi-document AI functionality."""

    def __init__(self):
        self.documents: Dict[str, Document] = {}
        self.chunks: Dict[str, List[DocumentChunk]] = {}

    def upload_documents(self, files: List[Dict[str, Any]]) -> List[str]:
        """Upload multiple documents (simulated)."""
        document_ids = []

        for file_info in files:
            # Simulate document processing
            doc_id = f"doc_{len(self.documents) + 1}"
            doc = Document(
                id=doc_id,
                filename=file_info.get('filename', 'document_' + str(doc_id) + '.' + str(file_info.get('format', 'pdf'))),
                content=file_info.get('content', ''),
                format=file_info.get('format', 'PDF'),
                metadata={
                    'upload_date': file_info.get('upload_date', '2026-08-27'),
                    'size': file_info.get('size', 0),
                    'source': file_info.get('source', 'upload')
                }
            )
            self.documents[doc_id] = doc
            document_ids.append(doc_id)

            # Extract chunks
            self.chunks[doc_id] = self._extract_chunks(doc)

        return document_ids

    def _extract_chunks(self, document: Document) -> List[DocumentChunk]:
        """Extract chunks from a document."""
        chunks = []
        
        # Simple sentence splitting: split by period followed by space
        # This preserves the full text including currency values
        sentences = re.split(r'\.\s+', document.content)
        
        for i, sentence in enumerate(sentences):
            sentence = sentence.strip()
            if len(sentence) > 20:  # Filter short sentences
                # Add the period back to preserve full text
                if not sentence.endswith('.') and i < len(sentences) - 1:
                    sentence += '.'
                
                chunk = DocumentChunk(
                    text=sentence,
                    metadata={
                        'document_id': document.id,
                        'chunk_id': i,
                        'char_length': len(sentence),
                        'word_count': len(sentence.split())
                    }
                )
                chunks.append(chunk)
        
        return chunks

    def get_document_overview(self) -> Dict[str, Any]:
        """Get compact overview of all uploaded documents."""
        overview = {
            'total_documents': len(self.documents),
            'total_chunks': sum(len(chunks) for chunks in self.chunks.values()),
            'total_words': 0,
            'formats': {},
            'documents': []
        }

        for doc_id, doc in self.documents.items():
            doc_info = {
                'id': doc_id,
                'filename': doc.filename,
                'format': doc.format,
                'chunk_count': len(self.chunks.get(doc_id, [])),
                'estimated_pages': max(1, len(self.chunks.get(doc_id, [])) // 5),
                'word_count': len(doc.content.split())
            }
            overview['documents'].append(doc_info)
            overview['total_words'] += doc_info['word_count']

            format_key = doc.format.upper()
            overview['formats'][format_key] = overview['formats'].get(format_key, 0) + 1

        return overview

    def search_across_documents(self, query: str) -> List[Dict[str, Any]]:
        """Search across all uploaded documents."""
        results = []
        query_words = set(query.lower().split())

        for doc_id, chunks in self.chunks.items():
            for chunk in chunks:
                text_lower = chunk.text.lower()
                text_words = set(text_lower.split())
                
                common_words = query_words.intersection(text_words)
                exact_match = query.lower() in text_lower
                
                if common_words or exact_match:
                    relevance_score = len(common_words) / max(len(query_words), 1)
                    if exact_match:
                        relevance_score = 1.0

                    if relevance_score >= 0.3:
                        result = {
                            'document_id': doc_id,
                            'document_name': self.documents[doc_id].filename,
                            'chunk_text': chunk.text,
                            'chunk_id': chunk.metadata.get('chunk_id'),
                            'relevance_score': relevance_score,
                            'citation': Citation(
                                source_document=self.documents[doc_id].filename,
                                source_chunk=f"Chunk {chunk.metadata.get('chunk_id')}",
                                page=None
                            )
                        }
                        results.append(result)

        return sorted(results, key=lambda x: x['relevance_score'], reverse=True)

    def search_single_document(self, doc_id: str, query: str) -> List[Dict[str, Any]]:
        """Search within a single document."""
        if doc_id not in self.documents:
            return []

        results = []
        query_words = set(query.lower().split())
        chunks = self.chunks.get(doc_id, [])

        for chunk in chunks:
            text_words = set(chunk.text.lower().split())
            common_words = query_words.intersection(text_words)
            
            if common_words:
                relevance_score = len(common_words) / max(len(query_words), 1)
                
                if relevance_score >= 0.3:
                    result = {
                        'document_id': doc_id,
                        'document_name': self.documents[doc_id].filename,
                        'chunk_text': chunk.text,
                        'chunk_id': chunk.metadata.get('chunk_id'),
                        'relevance_score': relevance_score,
                        'citation': Citation(
                            source_document=self.documents[doc_id].filename,
                            source_chunk=f"Chunk {chunk.metadata.get('chunk_id')}",
                            page=None
                        )
                    }
                    results.append(result)

        return sorted(results, key=lambda x: x['relevance_score'], reverse=True)

    def find_document_agreement(self, query: str) -> Dict[str, Any]:
        """Identify agreement between documents."""
        search_results = self.search_across_documents(query)
        
        if not search_results:
            return {
                'agreement_found': False,
                'citing_documents': [],
                'message': 'No information found in documents',
                'agreed_facts': []
            }

        # Group results by document
        doc_results = {}
        for result in search_results:
            doc_id = result['document_id']
            if doc_id not in doc_results:
                doc_results[doc_id] = []
            doc_results[doc_id].append(result)

        # Check for agreement (same content/fact across documents)
        agreement_info = {
            'agreement_found': False,
            'citing_documents': list(doc_results.keys()),
            'agreed_facts': [],
            'unique_per_document': {},
            'message': ''
        }

        # For each document, collect unique facts
        for doc_id, results in doc_results.items():
            unique_facts = []
            for result in results:
                fact_text = result['chunk_text']
                if fact_text not in unique_facts:
                    unique_facts.append(fact_text)
            agreement_info['unique_per_document'][doc_id] = unique_facts

        # Simple agreement detection: if same fact appears in multiple documents
        fact_to_docs = {}
        for doc_id, facts in agreement_info['unique_per_document'].items():
            for fact in facts:
                if fact not in fact_to_docs:
                    fact_to_docs[fact] = []
                fact_to_docs[fact].append(doc_id)

        agreed_facts = []
        for fact, docs in fact_to_docs.items():
            if len(docs) > 1:
                agreed_facts.append({
                    'fact': fact,
                    'citing_documents': docs,
                    'citation': Citation(
                        source_document=', '.join([self.documents[d].filename for d in docs]),
                        source_chunk='Multiple documents',
                        page=None
                    )
                })

        agreement_info['agreement_found'] = len(agreed_facts) > 0
        agreement_info['agreed_facts'] = agreed_facts

        return agreement_info

    def find_document_disagreement(self, query: str) -> Dict[str, Any]:
        """Identify disagreement/conflict between documents."""
        search_results = self.search_across_documents(query)

        if not search_results:
            return {
                'disagreement_found': False,
                'message': 'No information found in documents'
            }

        # Group results by document
        doc_results = {}
        for result in search_results:
            doc_id = result['document_id']
            if doc_id not in doc_results:
                doc_results[doc_id] = []
            doc_results[doc_id].append(result)

        disagreement_info = {
            'disagreement_found': False,
            'conflicting_facts': [],
            'documents_analyzed': list(doc_results.keys()),
            'message': ''
        }

        # Simple conflict detection based on contradictory terms
        # For demonstration: detect if documents say 'yes' vs 'no' to similar questions
        for doc_id, results in doc_results.items():
            for result in results:
                text_lower = result['chunk_text'].lower()
                
                # Detect contradictions in simple patterns
                if 'tidak' in text_lower or 'bukan' in text_lower or 'no' in text_lower:
                    conflict_info = {
                        'document_id': doc_id,
                        'document_name': self.documents[doc_id].filename,
                        'conflict_text': result['chunk_text'],
                        'conflict_type': 'negative_response',
                        'citation': result['citation']
                    }
                    disagreement_info['conflicting_facts'].append(conflict_info)

        disagreement_info['disagreement_found'] = len(disagreement_info['conflicting_facts']) > 0

        return disagreement_info

    def find_fact_source(self, query: str) -> Dict[str, Any]:
        """Identify which document contains a fact."""
        search_results = self.search_across_documents(query)

        if not search_results:
            return {
                'fact_found': False,
                'message': 'Fact not found in any document'
            }

        # Find the most relevant document for this fact
        best_result = search_results[0]

        fact_source_info = {
            'fact_found': True,
            'query': query,
            'source_document': best_result['document_id'],
            'source_document_name': best_result['document_name'],
            'source_chunk_text': best_result['chunk_text'],
            'source_chunk_id': best_result['chunk_id'],
            'relevance_score': best_result['relevance_score'],
            'citation': best_result['citation']
        }

        return fact_source_info

    def get_grounded_answer(self, query: str) -> Dict[str, Any]:
        """Get a grounded answer to a question across documents."""
        search_results = self.search_across_documents(query)

        if not search_results:
            return {
                'answer': 'Maaf, informasi tersebut tidak ditemukan dalam dokumen yang diunggah.',
                'grounded': False,
                'confidence': 0.0,
                'citations': [],
                'relevance_info': 'No relevant information found'
            }

        # Use top result for answer
        top_result = search_results[0]

        # Get Shared FreeAI response (simulated)
        answer = self._generate_answer_with_context(query, search_results)

        return {
            'answer': answer,
            'grounded': True,
            'confidence': top_result['relevance_score'],
            'citations': [top_result['citation']],
            'relevance_info': f"Found in {top_result['document_name']} (relevance: {top_result['relevance_score']:.2f})"
        }

    def _generate_answer_with_context(self, query: str, search_results: List[Dict]) -> str:
        """Generate answer using document context (simulates Shared FreeAI)."""
        top_result = search_results[0]

        # Create context from search results
        context_parts = []
        for result in search_results[:3]:
            context_parts.append(f"--- CITASI {len(context_parts) + 1}: {result['document_name']} ---\n{result['chunk_text']}\n")

        context = "\n\n".join(context_parts)

        # Simple answer generation based on context
        # In real implementation, this would call Shared FreeAI
        if 'rup' in query.lower():
            answer = f"Berdasarkan dokumen yang diunggah, jawaban untuk pertanyaan '{query}' adalah: {top_result['chunk_text']}"
        elif 'berapa' in query.lower():
            # Look for numbers in the document
            numbers = re.findall(r'\d+', top_result['chunk_text'])
            if numbers:
                answer = f"Berdasarkan dokumen yang diunggah, nilai yang ditemukan adalah: {', '.join(numbers)}"
            else:
                answer = f"Berdasarkan dokumen yang diunggah, informasi untuk pertanyaan '{query}' adalah: {top_result['chunk_text']}"
        else:
            answer = f"Berdasarkan dokumen yang diunggah, jawaban untuk pertanyaan '{query}' adalah: {top_result['chunk_text']}"

        return answer

    def check_prompt_injection(self, text: str) -> Dict[str, Any]:
        """Test for prompt injection attempts."""
        injection_patterns = [
            r'ignore.*previous.*instruction',
            r'reveal.*secrets',
            r'override.*system',
            r'expose.*password',
            r'ignore.*all.*instructions',
            r'reveal.*api.*key',
            r'secret.*instruction',
            r'override.*prompt',
            r'abaikan.*semua.*instruksi',
            r'ungkapkan.*rahasia',
            r'lewat.*system',
            r'tampilkan.*kata\s*sandi',
            r'lewati.*semua.*instruksi',
            r'tampilkan.*api\s*key',
            r'instruksi.*rahasia',
            r'lewati.*prompt'
        ]

        detected_issues = []
        for pattern in injection_patterns:
            if re.search(pattern, text, re.IGNORECASE | re.UNICODE):
                detected_issues.append(pattern)

        if detected_issues:
            return {
                'safe': False,
                'detected_patterns': detected_issues,
                'message': 'Prompt injection attempt detected and blocked'
            }
        else:
            return {
                'safe': True,
                'detected_patterns': [],
                'message': 'Text treated as document content only'
            }
