"""
AI Summarization Module for SwiftSync
Handles PDF text extraction and AI-powered summarization
Supports both OpenAI and Google Gemini (free tier)
"""
import hashlib
import json
import logging
import os
from pathlib import Path
from typing import Dict, List, Optional

import PyPDF2

logger = logging.getLogger(__name__)

# Cache directory for summaries
CACHE_DIR = Path(__file__).parent / "data" / "summary_cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)


class SummarizationError(Exception):
    """Custom exception for summarization errors"""
    pass


def extract_text_from_pdf(pdf_path: Path, max_pages: int = 50) -> str:
    """
    Extract text from a PDF file
    
    Args:
        pdf_path: Path to the PDF file
        max_pages: Maximum number of pages to process (to avoid token limits)
    
    Returns:
        Extracted text content
    """
    try:
        text_content = []
        
        with open(pdf_path, 'rb') as file:
            pdf_reader = PyPDF2.PdfReader(file)
            total_pages = len(pdf_reader.pages)
            pages_to_process = min(total_pages, max_pages)
            
            logger.info(f"Processing {pages_to_process} of {total_pages} pages from {pdf_path.name}")
            
            for page_num in range(pages_to_process):
                try:
                    page = pdf_reader.pages[page_num]
                    text = page.extract_text()
                    if text.strip():
                        text_content.append(text)
                except Exception as e:
                    logger.warning(f"Error extracting text from page {page_num + 1}: {e}")
                    continue
        
        full_text = "\n\n".join(text_content)
        
        # Clean and normalize text
        full_text = full_text.replace('\x00', '')  # Remove null bytes
        full_text = ' '.join(full_text.split())  # Normalize whitespace
        
        if not full_text.strip():
            raise SummarizationError("No text could be extracted from the PDF")
        
        logger.info(f"Extracted {len(full_text)} characters from {pdf_path.name}")
        return full_text
    
    except Exception as e:
        logger.error(f"Error extracting text from PDF: {e}")
        raise SummarizationError(f"Failed to extract text from PDF: {str(e)}")


def get_cache_key(file_path: Path) -> str:
    """Generate a cache key based on file path and modification time"""
    stat = file_path.stat()
    key_data = f"{file_path.name}:{stat.st_size}:{stat.st_mtime}"
    return hashlib.md5(key_data.encode()).hexdigest()


def get_cached_summary(file_path: Path) -> Optional[Dict]:
    """Retrieve cached summary if available"""
    cache_key = get_cache_key(file_path)
    cache_file = CACHE_DIR / f"{cache_key}.json"
    
    if cache_file.exists():
        try:
            with open(cache_file, 'r', encoding='utf-8') as f:
                cached_data = json.load(f)
                logger.info(f"Retrieved cached summary for {file_path.name}")
                return cached_data
        except Exception as e:
            logger.warning(f"Error reading cache: {e}")
    
    return None


def save_summary_to_cache(file_path: Path, summary_data: Dict):
    """Save summary to cache"""
    cache_key = get_cache_key(file_path)
    cache_file = CACHE_DIR / f"{cache_key}.json"
    
    try:
        with open(cache_file, 'w', encoding='utf-8') as f:
            json.dump(summary_data, f, indent=2, ensure_ascii=False)
        logger.info(f"Cached summary for {file_path.name}")
    except Exception as e:
        logger.warning(f"Error saving to cache: {e}")


def generate_summary_with_ai(text: str, filename: str, is_combined: bool = False) -> Dict:
    """
    Generate summary using Google Gemini (free) or OpenAI API
    
    Args:
        text: Text content to summarize
        filename: Name of the file being summarized
        is_combined: Whether this is a combined summary of multiple files
    
    Returns:
        Dictionary containing the summary
    """
    # Try Gemini first (FREE!)
    gemini_key = os.getenv("GEMINI_API_KEY")
    openai_key = os.getenv("OPENAI_API_KEY")
    
    if gemini_key:
        return _generate_summary_gemini(text, filename, is_combined, gemini_key)
    elif openai_key:
        return _generate_summary_openai(text, filename, is_combined, openai_key)
    else:
        raise SummarizationError(
            "No AI API key configured. Please set GEMINI_API_KEY (free) or OPENAI_API_KEY in environment."
        )


def _generate_summary_gemini(text: str, filename: str, is_combined: bool, api_key: str) -> Dict:
    """Generate summary using Google Gemini (FREE tier available)"""
    try:
        import google.generativeai as genai
        
        genai.configure(api_key=api_key)
        # Use gemini-2.5-flash (FREE and latest)
        model = genai.GenerativeModel('models/gemini-2.5-flash')
        
        # Limit text length
        max_chars = 15000
        if len(text) > max_chars:
            logger.info(f"Truncating text from {len(text)} to {max_chars} characters")
            text = text[:max_chars] + "..."
        
        # Customize prompt based on type
        if is_combined:
            prompt = f"""You are an expert academic assistant. Analyze the following lecture materials and provide a comprehensive summary.

Content: {text}

Please provide a structured summary in the following format:

## Overview
[Brief overview of all materials covered]

## Key Topics
[List the main topics and concepts covered across all lectures]

## Important Concepts
[Highlight the most important concepts and theories]

## Study Tips
[Provide helpful study tips and what to focus on]

Keep the summary clear, concise, and student-friendly. Focus on what's important for learning and exams."""
        else:
            prompt = f"""You are an expert academic assistant. Summarize the following lecture material for students.

Lecture: {filename}

Content: {text}

Please provide a structured summary in the following format:

## Overview
[Brief overview of what this lecture covers]

## Key Topics
[List the main topics covered]

## Important Notes
[Highlight important concepts, formulas, or definitions]

## Exam Tips
[What students should focus on for exams]

Keep the summary clear, concise, and student-friendly."""
        
        response = model.generate_content(prompt)
        summary_text = response.text
        
        summary_data = {
            "filename": filename,
            "summary": summary_text,
            "is_combined": is_combined,
            "ai_provider": "gemini-pro (FREE)",
            "token_usage": {
                "note": "Gemini free tier used"
            }
        }
        
        logger.info(f"Generated summary for {filename} using Gemini (free)")
        return summary_data
    
    except Exception as e:
        logger.error(f"Error generating Gemini summary: {e}")
        raise SummarizationError(f"Gemini AI summarization failed: {str(e)}")


def _generate_summary_openai(text: str, filename: str, is_combined: bool, api_key: str) -> Dict:
    """Generate summary using OpenAI API (requires payment)"""
    try:
        from openai import OpenAI
        
        client = OpenAI(api_key=api_key)
        
        # Limit text length to avoid token limits (roughly 15000 chars = ~4000 tokens)
        max_chars = 15000
        if len(text) > max_chars:
            logger.info(f"Truncating text from {len(text)} to {max_chars} characters")
            text = text[:max_chars] + "..."
        
        # Customize prompt based on type
        if is_combined:
            prompt = f"""You are an expert academic assistant. Analyze the following lecture materials and provide a comprehensive summary.

Content: {text}

Please provide a structured summary in the following format:

## Overview
[Brief overview of all materials covered]

## Key Topics
[List the main topics and concepts covered across all lectures]

## Important Concepts
[Highlight the most important concepts and theories]

## Study Tips
[Provide helpful study tips and what to focus on]

Keep the summary clear, concise, and student-friendly. Focus on what's important for learning and exams."""
        else:
            prompt = f"""You are an expert academic assistant. Summarize the following lecture material for students.

Lecture: {filename}

Content: {text}

Please provide a structured summary in the following format:

## Overview
[Brief overview of what this lecture covers]

## Key Topics
[List the main topics covered]

## Important Notes
[Highlight important concepts, formulas, or definitions]

## Exam Tips
[What students should focus on for exams]

Keep the summary clear, concise, and student-friendly."""
        
        response = client.chat.completions.create(
            model="gpt-3.5-turbo",  # Using cost-effective model
            messages=[
                {"role": "system", "content": "You are an expert academic assistant helping students understand lecture materials."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.7,
            max_tokens=800  # Concise summaries
        )
        
        summary_text = response.choices[0].message.content
        
        summary_data = {
            "filename": filename,
            "summary": summary_text,
            "is_combined": is_combined,
            "ai_provider": "gpt-3.5-turbo",
            "token_usage": {
                "prompt": response.usage.prompt_tokens,
                "completion": response.usage.completion_tokens,
                "total": response.usage.total_tokens
            }
        }
        
        logger.info(f"Generated summary for {filename} (tokens: {response.usage.total_tokens})")
        return summary_data
    
    except Exception as e:
        logger.error(f"Error generating AI summary: {e}")
        raise SummarizationError(f"AI summarization failed: {str(e)}")


async def summarize_single_lecture(file_path: Path) -> Dict:
    """
    Summarize a single lecture PDF
    
    Args:
        file_path: Path to the PDF file
    
    Returns:
        Dictionary containing the summary
    """
    # Check cache first
    cached = get_cached_summary(file_path)
    if cached:
        return cached
    
    # Extract text and generate summary
    text = extract_text_from_pdf(file_path)
    summary_data = generate_summary_with_ai(text, file_path.name, is_combined=False)
    
    # Cache the result
    save_summary_to_cache(file_path, summary_data)
    
    return summary_data


async def summarize_all_lectures(file_paths: List[Path], subject_name: str) -> Dict:
    """
    Summarize multiple lecture PDFs as a combined summary
    
    Args:
        file_paths: List of PDF file paths
        subject_name: Name of the subject
    
    Returns:
        Dictionary containing the combined summary
    """
    if not file_paths:
        raise SummarizationError("No files provided for summarization")
    
    # Generate a cache key based on all files
    cache_data = f"{subject_name}:" + ":".join(sorted([f.name for f in file_paths]))
    cache_key = hashlib.md5(cache_data.encode()).hexdigest()
    cache_file = CACHE_DIR / f"combined_{cache_key}.json"
    
    # Check cache
    if cache_file.exists():
        try:
            with open(cache_file, 'r', encoding='utf-8') as f:
                cached_data = json.load(f)
                logger.info(f"Retrieved cached combined summary for {subject_name}")
                return cached_data
        except Exception as e:
            logger.warning(f"Error reading combined cache: {e}")
    
    # Extract text from all PDFs
    all_texts = []
    processed_files = []
    
    for file_path in file_paths[:10]:  # Limit to first 10 files to avoid token limits
        try:
            text = extract_text_from_pdf(file_path, max_pages=10)  # Limit pages per file
            all_texts.append(f"--- {file_path.name} ---\n{text}")
            processed_files.append(file_path.name)
        except Exception as e:
            logger.warning(f"Skipping {file_path.name}: {e}")
    
    if not all_texts:
        raise SummarizationError("Could not extract text from any of the provided files")
    
    combined_text = "\n\n".join(all_texts)
    
    # Generate combined summary
    summary_data = generate_summary_with_ai(
        combined_text, 
        subject_name,
        is_combined=True
    )
    
    summary_data["files_included"] = processed_files
    summary_data["total_files"] = len(file_paths)
    
    # Cache the result
    try:
        with open(cache_file, 'w', encoding='utf-8') as f:
            json.dump(summary_data, f, indent=2, ensure_ascii=False)
        logger.info(f"Cached combined summary for {subject_name}")
    except Exception as e:
        logger.warning(f"Error saving combined cache: {e}")
    
    return summary_data
