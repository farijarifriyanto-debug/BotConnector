# OLAHDOKUMEN FREE FEATURES V2 - Document Comparison Engine
# Backend implementation for comparing documents with similarities and differences detection

import os
import json
import re
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass
from pathlib import Path

@dataclass
class ComparisonResult:
    """Result of comparing two documents."""
    similarities: List[str]
    differences: List[str]
    added: List[str]
    removed: List[str]
    changed: List[Dict[str, Any]]
    changed_numbers: List[Dict[str, Any]]
    changed_money_values: List[Dict[str, Any]]
    changed_percentages: List[Dict[str, Any]]
    changed_dates: List[Dict[str, Any]]
    citations: List[Dict[str, Any]]

class DocumentComparator:
    """Core class for document comparison functionality."""

    def __init__(self):
        pass

    def compare_documents(self, doc_a: Dict[str, Any], doc_b: Dict[str, Any]) -> ComparisonResult:
        """Compare two documents and return detailed comparison results.

        Args:
            doc_a: First document with 'content' field
            doc_b: Second document with 'content' field

        Returns:
            ComparisonResult object with similarities, differences, added, removed, etc.
        """
        content_a = doc_a.get('content', '')
        content_b = doc_b.get('content', '')

        if not content_a or not content_b:
            return ComparisonResult(
                similarities=[],
                differences=[f"Document A: {content_a}", f"Document B: {content_b}"],
                added=[],
                removed=[],
                changed=[],
                changed_numbers=[],
                changed_money_values=[],
                changed_percentages=[],
                changed_dates=[],
                citations=[]
            )

        # Split into sentences
        sentences_a = self._split_into_sentences(content_a)
        sentences_b = self._split_into_sentences(content_b)

        # Find similarities
        similarities = self._find_similarities(sentences_a, sentences_b)

        # Find differences
        differences = self._find_differences(sentences_a, sentences_b)

        # Find added content
        added = self._find_added_content(sentences_a, sentences_b)

        # Find removed content
        removed = self._find_removed_content(sentences_a, sentences_b)

        # Find changed content
        changed = self._find_changed_content(sentences_a, sentences_b)

        # Find specific changes
        changed_numbers = self._find_numeric_changes(sentences_a, sentences_b)
        changed_money_values = self._find_money_value_changes(sentences_a, sentences_b)
        changed_percentages = self._find_percentage_changes(sentences_a, sentences_b)
        changed_dates = self._find_date_changes(sentences_a, sentences_b)

        # Generate citations
        citations = self._generate_citations(doc_a, doc_b)

        return ComparisonResult(
            similarities=similarities,
            differences=differences,
            added=added,
            removed=removed,
            changed=changed,
            changed_numbers=changed_numbers,
            changed_money_values=changed_money_values,
            changed_percentages=changed_percentages,
            changed_dates=changed_dates,
            citations=citations
        )

    def _split_into_sentences(self, text: str) -> List[str]:
        """Split text into sentences, preserving important patterns."""
        if not text:
            return []

        # First, replace newlines with spaces
        text = text.replace('\n', ' ')

        # Split by period followed by space or end of string
        sentences = re.split(r'\.\s+', text)

        # Clean up sentences
        cleaned_sentences = []
        for sentence in sentences:
            sentence = sentence.strip()
            if sentence:
                # Add period back if missing
                if not sentence.endswith('.'):
                    sentence += '.'

                # Keep sentences that are meaningful - slightly larger threshold
                if len(sentence) >= 15:
                    cleaned_sentences.append(sentence)

        return cleaned_sentences

    def _find_similarities(self, sentences_a: List[str], sentences_b: List[str]) -> List[str]:
        """Find sentences that are similar or identical."""
        similarities = []

        for sent_a in sentences_a:
            for sent_b in sentences_b:
                similarity = self._calculate_similarity(sent_a, sent_b)
                if similarity > 0.8:  # High similarity threshold
                    similarities.append(f"A: {sent_a}\nB: {sent_b}")

        return similarities

    def _find_differences(self, sentences_a: List[str], sentences_b: List[str]) -> List[str]:
        """Find sentences that are different."""
        differences = []

        for sent_a in sentences_a:
            for sent_b in sentences_b:
                similarity = self._calculate_similarity(sent_a, sent_b)
                if similarity <= 0.3:  # Different threshold
                    differences.append(f"A: {sent_a}\nB: {sent_b}")

        return differences

    def _find_added_content(self, sentences_a: List[str], sentences_b: List[str]) -> List[str]:
        """Find content that exists only in Document B (added)."""
        added = []

        for sent_b in sentences_b:
            found_in_a = False
            for sent_a in sentences_a:
                if self._calculate_similarity(sent_a, sent_b) > 0.7:
                    found_in_a = True
                    break
            if not found_in_a:
                added.append(sent_b)

        return added

    def _find_removed_content(self, sentences_a: List[str], sentences_b: List[str]) -> List[str]:
        """Find content that exists only in Document A (removed from B's perspective)."""
        removed = []

        for sent_a in sentences_a:
            found_in_b = False
            for sent_b in sentences_b:
                if self._calculate_similarity(sent_a, sent_b) > 0.7:
                    found_in_b = True
                    break
            if not found_in_b:
                removed.append(sent_a)

        return removed

    def _find_changed_content(self, sentences_a: List[str], sentences_b: List[str]) -> List[Dict[str, Any]]:
        """Find content that has changed between documents."""
        changed = []

        for sent_a in sentences_a:
            for sent_b in sentences_b:
                similarity = self._calculate_similarity(sent_a, sent_b)
                if 0.3 < similarity <= 0.7:  # Moderately similar but not identical
                    changed.append({
                        'original': sent_a,
                        'changed': sent_b,
                        'similarity': similarity
                    })

        return changed

    def _find_numeric_changes(self, sentences_a: List[str], sentences_b: List[str]) -> List[Dict[str, Any]]:
        """Find numeric value changes between documents."""
        changed_numbers = []

        # Pattern for numbers (including decimals and whole numbers)
        number_pattern = r'\d+'

        # Check all sentences from both documents
        all_sentences = []
        for sent in sentences_a:
            all_sentences.append(('A', sent))
        for sent in sentences_b:
            all_sentences.append(('B', sent))

        # For each unique number, find its occurrences and values
        for sentence_type, sentence in all_sentences:
            numbers_in_sentence = re.findall(number_pattern, sentence)

            for num in numbers_in_sentence:
                # Convert to int for comparison
                try:
                    num_val = int(num)
                except ValueError:
                    try:
                        num_val = float(num)
                    except ValueError:
                        continue

                # Find this number in other sentences
                for other_type, other_sentence in all_sentences:
                    other_numbers = re.findall(number_pattern, other_sentence)

                    for other_num in other_numbers:
                        try:
                            other_val = int(other_num)
                        except ValueError:
                            try:
                                other_val = float(other_num)
                            except ValueError:
                                continue

                        # Check if the values are different
                        if num_val != other_val:
                            # Only add if we haven't already added this comparison
                            found = False
                            for existing in changed_numbers:
                                if ((existing['original'] == num and existing['changed'] == other_num) or
                                    (existing['original'] == other_num and existing['changed'] == num)):
                                    found = True
                                    break

                            if not found:
                                changed_numbers.append({
                                    'document_a': sentence if sentence_type == 'A' else None,
                                    'document_b': sentence if sentence_type == 'B' else None,
                                    'original': num,
                                    'changed': other_num,
                                    'type': 'number'
                                })

        return changed_numbers

    def _find_money_value_changes(self, sentences_a: List[str], sentences_b: List[str]) -> List[Dict[str, Any]]:
        """Find money value changes between documents."""
        changed_money = []

        # Better money pattern that matches complete values like Rp100.000.000
        money_pattern = r'Rp\d{1,3}(?:,\d{3})*(?:\.\d{3})*'

        for sent_a in sentences_a:
            for sent_b in sentences_b:
                money_a = re.findall(money_pattern, sent_a)
                money_b = re.findall(money_pattern, sent_b)

                for val_a in money_a:
                    for val_b in money_b:
                        # Clean and compare money values
                        clean_a = re.sub(r'Rp|,|\\.', '', val_a)
                        clean_b = re.sub(r'Rp|,|\\.', '', val_b)

                        if clean_a != clean_b:
                            changed_money.append({
                                'document_a': sent_a,
                                'document_b': sent_b,
                                'original': val_a,
                                'changed': val_b,
                                'type': 'money_value'
                            })

        return changed_money

    def _find_percentage_changes(self, sentences_a: List[str], sentences_b: List[str]) -> List[Dict[str, Any]]:
        """Find percentage value changes between documents."""
        changed_percentages = []

        percent_pattern = r'\d+%'

        for sent_a in sentences_a:
            for sent_b in sentences_b:
                percents_a = re.findall(percent_pattern, sent_a)
                percents_b = re.findall(percent_pattern, sent_b)

                for val_a in percents_a:
                    for val_b in percents_b:
                        clean_a = re.sub(r'%', '', val_a)
                        clean_b = re.sub(r'%', '', val_b)

                        if clean_a != clean_b:
                            changed_percentages.append({
                                'document_a': sent_a,
                                'document_b': sent_b,
                                'original': val_a,
                                'changed': val_b,
                                'type': 'percentage'
                            })

        return changed_percentages

    def _find_date_changes(self, sentences_a: List[str], sentences_b: List[str]) -> List[Dict[str, Any]]:
        """Find date value changes between documents."""
        changed_dates = []

        date_pattern = r'\d{1,2}\s+(?:Jan|Feb|Mar|Apr|Mei|Jun|Jul|Aug|Sep|Oct|Nov|Des)\s+\d{4}'

        for sent_a in sentences_a:
            for sent_b in sentences_b:
                dates_a = re.findall(date_pattern, sent_a, re.IGNORECASE)
                dates_b = re.findall(date_pattern, sent_b, re.IGNORECASE)

                for val_a in dates_a:
                    for val_b in dates_b:
                        if val_a != val_b:
                            changed_dates.append({
                                'document_a': sent_a,
                                'document_b': sent_b,
                                'original': val_a,
                                'changed': val_b,
                                'type': 'date'
                            })

        return changed_dates

    def _calculate_similarity(self, sent_a: str, sent_b: str) -> float:
        """Calculate similarity between two sentences."""
        if sent_a == sent_b:
            return 1.0

        # Simple word-based similarity
        words_a = set(sent_a.lower().split())
        words_b = set(sent_b.lower().split())

        if not words_a and not words_b:
            return 1.0

        intersection = len(words_a.intersection(words_b))
        union = len(words_a.union(words_b))

        return intersection / union if union > 0 else 0.0

    def _generate_citations(self, doc_a: Dict[str, Any], doc_b: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Generate citations for comparison results."""
        citations = []

        if doc_a.get('filename'):
            citations.append({
                'source_document': doc_a['filename'],
                'source_chunk': f"Document A: {doc_a.get('filename', 'Unknown')}",
                'page': None
            })

        if doc_b.get('filename'):
            citations.append({
                'source_document': doc_b['filename'],
                'source_chunk': f"Document B: {doc_b.get('filename', 'Unknown')}",
                'page': None
            })

        return citations
