# AI Lecture Summarization Feature

## Overview

SwiftSync now includes an **AI-powered lecture summarization feature** that helps students quickly understand and review lecture content. This feature uses OpenAI's GPT models to generate clear, concise summaries of PDF lecture materials.

## Features

### 1. Single Lecture Summary
- Click **"Get Summary"** button next to any PDF lecture
- AI analyzes the PDF content and generates a structured summary
- Results are displayed in a clean, modern modal
- Summaries are cached for faster retrieval

### 2. Multi-Lecture Summary ("Summarize All")
- Click **"Summarize All Lectures"** at the bottom of any subject section
- AI analyzes all PDFs in that subject together
- Generates a comprehensive overview of the entire subject
- Identifies key topics and important concepts across all lectures

## Summary Structure

Each AI-generated summary includes:

- **Overview**: Brief introduction to the lecture content
- **Key Topics**: Main topics and concepts covered
- **Important Notes**: Critical concepts, formulas, or definitions
- **Exam Tips**: What students should focus on for exams (single lectures)
- **Study Tips**: Helpful study recommendations (combined summaries)

## Setup Instructions

### 1. Install Dependencies

```bash
pip install -r requirements.txt
```

New dependencies added:
- `PyPDF2` - PDF text extraction
- `openai` - OpenAI API integration
- `aiofiles` - Async file operations

### 2. Configure OpenAI API Key

Get your API key from [OpenAI Platform](https://platform.openai.com/api-keys)

Add to your `.env` file:
```env
OPENAI_API_KEY=your_actual_api_key_here
```

### 3. Start the Server

```bash
python main.py
```

Or use your existing deployment method.

## Usage Guide

### For Students

1. **Navigate** to SwiftSync dashboard
2. **Browse** to find the lecture you want to summarize
3. **Click** "Get Summary" for individual lectures
4. **Click** "Summarize All Lectures" for subject-wide summaries
5. **Read** the AI-generated summary in the modal
6. **Close** the modal when done (click X, outside modal, or press ESC)

### Important Notes

- ✅ Only PDF files can be summarized
- ✅ Summaries are cached for faster retrieval
- ✅ First summarization may take 10-30 seconds
- ✅ Subsequent requests for the same file are instant
- ✅ Works offline after cache is populated

## Technical Details

### API Endpoints

#### POST `/api/summarize`
Summarize a single lecture PDF

**Query Parameters:**
- `filename` (string, required) - Name of the PDF file

**Response:**
```json
{
  "success": true,
  "data": {
    "filename": "lecture1.pdf",
    "summary": "...",
    "is_combined": false,
    "token_usage": {
      "prompt": 1500,
      "completion": 600,
      "total": 2100
    }
  }
}
```

#### POST `/api/summarize-all`
Summarize all lectures in a subject

**Query Parameters:**
- `subject` (string, required) - Name of the subject

**Response:**
```json
{
  "success": true,
  "data": {
    "filename": "Subject Name",
    "summary": "...",
    "is_combined": true,
    "files_included": ["lecture1.pdf", "lecture2.pdf"],
    "total_files": 2,
    "token_usage": {
      "prompt": 3000,
      "completion": 800,
      "total": 3800
    }
  }
}
```

### Architecture

```
┌─────────────┐
│   Browser   │ (UI with new buttons)
└──────┬──────┘
       │ HTTP POST
       ▼
┌─────────────┐
│  FastAPI    │ (main.py - new endpoints)
└──────┬──────┘
       │
       ▼
┌─────────────┐
│ summarizer  │ (AI logic)
│   .py       │
└──────┬──────┘
       │
       ├─────► PyPDF2 (text extraction)
       │
       ├─────► OpenAI API (summarization)
       │
       └─────► Cache (data/summary_cache/)
```

### Caching Strategy

- **Cache Key**: MD5 hash of `filename:filesize:modification_time`
- **Cache Location**: `data/summary_cache/*.json`
- **Cache Invalidation**: Automatic when file is modified
- **Performance**: Instant retrieval for cached summaries

### Performance Optimizations

1. **Text Truncation**: Long PDFs are truncated to ~15,000 characters
2. **Page Limiting**: 
   - Single lectures: max 50 pages
   - Combined summaries: max 10 pages per file, max 10 files
3. **Async Processing**: Non-blocking API calls
4. **Smart Caching**: Reduces API costs and latency

### Cost Management

Using **GPT-3.5-turbo** for cost efficiency:
- Average cost per summary: $0.002 - $0.005
- Typical token usage: 2,000-4,000 tokens
- Cached summaries: $0 (instant retrieval)

## Error Handling

Graceful error handling for:
- ❌ Missing OpenAI API key → Clear error message
- ❌ PDF extraction failure → Helpful error displayed
- ❌ API rate limits → User-friendly message
- ❌ Network issues → Retry guidance
- ❌ Empty PDFs → "No text could be extracted" message

## Security & Privacy

- ✅ PDFs are read-only (no modifications)
- ✅ No permanent storage of AI results (only cache)
- ✅ API key stored securely in environment variables
- ✅ No data sent to third parties except OpenAI
- ✅ Cache can be cleared at any time

## UI/UX Design

### Design Principles
- **Non-Breaking**: Existing UI remains unchanged
- **Consistent**: Buttons match existing design language
- **Accessible**: Clear visual feedback and loading states
- **Responsive**: Works on mobile and desktop

### Visual Elements
- **Get Summary Button**: Purple gradient (distinguishes from Download)
- **Summarize All Button**: Pink/red gradient (stands out as subject-level action)
- **Modal**: Dark theme matching SwiftSync design
- **Loading State**: Animated spinner with helpful message
- **Error State**: Clear error messages with icon

## Maintenance

### Cache Management

Clear cache manually:
```bash
rm -rf data/summary_cache/*
```

Or programmatically in Python:
```python
from pathlib import Path
cache_dir = Path("data/summary_cache")
for cache_file in cache_dir.glob("*.json"):
    cache_file.unlink()
```

### Monitoring

Check logs for:
- API usage and token consumption
- Cache hit/miss rates
- Error patterns
- Processing times

## Troubleshooting

### "OpenAI API key not configured"
**Solution**: Add `OPENAI_API_KEY` to your `.env` file

### "No text could be extracted from the PDF"
**Solution**: PDF may be image-based or corrupted. Use OCR or re-download.

### Slow summarization
**Solution**: 
- Check internet connection
- Verify OpenAI API status
- Consider reducing PDF size/pages

### High API costs
**Solution**:
- Cache is working automatically
- Consider using GPT-3.5-turbo (already default)
- Limit pages processed per PDF

## Future Enhancements

Potential improvements:
- 🔮 Support for OCR (image-based PDFs)
- 🔮 Multiple language support
- 🔮 Custom summary length options
- 🔮 Export summaries as PDF/Word
- 🔮 Study plan generation
- 🔮 Quiz generation from lectures
- 🔮 Comparison between lectures

## Support

For issues or questions:
1. Check error messages in the modal
2. Review browser console for details
3. Check server logs for backend errors
4. Verify OpenAI API key is valid

## License

This feature is part of SwiftSync by SSCreative.

---

**Version**: 1.0.0  
**Date**: January 2026  
**Status**: ✅ Production Ready
