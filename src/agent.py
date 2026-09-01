import re
from typing import List, Dict, Any, Optional

class AgentRuntime:
    def __init__(self):
        pass

    def _filter_relevant_candidates(self, candidates: List[Dict], question: str) -> List[Dict]:
        """Filter candidates based on relevance to the question."""
        relevant = []

        # Normalize question: remove punctuation, convert to lowercase
        normalized_question = ''.join(c for c in question.lower() if c.isalnum() or c.isspace())
        question_words = set(normalized_question.split())

        for candidate in candidates:
            text = candidate.get('text', '').lower()

            # Normalize text: remove punctuation, convert to lowercase
            normalized_text = ''.join(c for c in text if c.isalnum() or c.isspace())
            text_words = set(normalized_text.split())

            # Simple relevance calculation
            common_words = question_words.intersection(text_words)
            relevance_score = len(common_words) / max(len(question_words), 1)

            # Use the existing relevance threshold from spec
            if relevance_score >= 0.3:  # THRESHOLD from specs
                relevant.append({
                    'text': normalized_text,
                    'score': relevance_score,
                    'citation': candidate.get('citation'),
                    'source': candidate.get('source', 'document')
                })

        return sorted(relevant, key=lambda x: x['score'], reverse=True)

    def _call_shared_freeai_with_candidates(self, candidates: List[Dict], question: str, provider_config=None):
        """Call Shared FreeAI with relevant candidates."""
        try:
            # Prepare context for AI
            context_parts = []
            citations = []

            for candidate in candidates[:3]:  # Limit to top 3 candidates for efficiency
                context_parts.append(f"--- CITASI {len(citations) + 1}: {candidate.get('source', '')} ---\n{candidate['text']}\n")
                citations.append({
                    'text': candidate['text'],
                    'source': candidate.get('source', ''),
                    'score': candidate['score']
                })

            context = "\n\n".join(context_parts)

            # Call Shared FreeAI (implement Shared FreeAI integration)
            # For demonstration, simulate the AI response
            if candidates:
                top_candidate = candidates[0]
                answer = f"Berdasarkan dokumen yang diunggah, jawaban untuk pertanyaan '{question}' adalah: {top_candidate['text'][:200]}..."
                confidence = top_candidate['score']
                grounded = True
            else:
                answer = "Maaf, informasi tersebut tidak ditemukan dalam dokumen yang diunggah."
                confidence = 0.0
                grounded = False

            return {
                "answer": answer,
                "citations": citations,
                "provider": provider_config.get('provider') if provider_config else None,
                "model": provider_config.get('model') if provider_config else None,
                "confidence": confidence,
                "grounded": grounded
            }
        except Exception as e:
            return {
                "answer": f"Maaf, terjadi kesalahan saat memproses pertanyaan Anda: {str(e)}",
                "citations": [],
                "provider": None,
                "model": None,
                "confidence": 0.0,
                "grounded": False
            }

    def build_ai_answer(self, question, candidates, provider_config=None):
        """Build AI answer from candidates using Shared FreeAI."""
        if not candidates:
            return {
                "answer": "Maaf, informasi tersebut tidak ditemukan dalam dokumen yang diunggah.",
                "citations": [],
                "provider": None,
                "model": None,
                "confidence": 0.0,
                "grounded": False
            }

        # Check relevance threshold BEFORE calling AI - FIXED: moved BEFORE AI return
        relevant_candidates = self._filter_relevant_candidates(candidates, question)

        if not relevant_candidates:
            return {
                "answer": "Maaf, informasi tersebut tidak ditemukan dalam dokumen yang diunggah.",
                "citations": [],
                "provider": None,
                "model": None,
                "confidence": 0.0,
                "grounded": False
            }

        # Call Shared FreeAI with relevant candidates
        return self._call_shared_freeai_with_candidates(relevant_candidates, question, provider_config)

    def tanya_document(self, question, document_text, provider_config=None):
        """Main Tanya Dokumen function."""
        # Extract candidates from document
        candidates = self._extract_candidates_from_document(document_text)

        # Build AI answer with proper relevance filtering
        return self.build_ai_answer(question, candidates, provider_config)

    def _extract_candidates_from_document(self, document_text):
        """Extract relevant candidates from document text."""
        # Simple sentence extraction for demonstration
        sentences = re.split(r'[.!?]+\s*', document_text)
        candidates = []

        for i, sentence in enumerate(sentences):
            if len(sentence.strip()) > 20:  # Filter short sentences
                candidates.append({
                    'text': sentence.strip(),
                    'citation': f'Sentence {i+1}',
                    'source': 'document'
                })

        return candidates

    def process_tanya_query(self, query, context=None):
        """Process Tanya query with full relevance filtering."""
        if not context:
            return {
                "answer": "Maaf, tidak ada konteks dokumen yang disediakan.",
                "citations": [],
                "provider": None,
                "model": None,
                "confidence": 0.0,
                "grounded": False
            }

        # Extract candidates from context
        candidates = self._extract_candidates_from_document(context)

        # Determine if question is relevant
        is_irrelevant = self._check_question_relevance(query, context)

        if is_irrelevant:
            return {
                "answer": "Maaf, informasi tersebut tidak ditemukan dalam dokumen yang diunggah.",
                "citations": [],
                "provider": None,
                "model": None,
                "confidence": 0.0,
                "grounded": False
            }

        # Process relevant question
        return self.build_ai_answer(query, candidates)

    def _check_question_relevance(self, question, document_text):
        """Check if question is relevant to document content."""
        question_words = set(question.lower().split())
        document_words = set(document_text.lower().split())

        # Calculate overlap
        overlap = question_words.intersection(document_words)
        relevance_ratio = len(overlap) / max(len(question_words), 1)

        # Consider irrelevant if overlap is very small
        return relevance_ratio < 0.05
