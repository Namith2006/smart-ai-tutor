from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import PyPDF2, io, requests, json, re

app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

session_errors = []

class StudyRequest(BaseModel):
    content: str
    mode: str 
    preferences: list[str]

class FeedbackRequest(BaseModel):
    concept: str
    is_correct: bool

class TopicRequest(BaseModel):
    topic: str
    stream: str
    year: str
    university: str

# --- HELPER: SORT UNITS NUMERICALLY ---
def sort_by_unit(items):
    def extract_unit_number(text):
        match = re.search(r"Unit\s+(\d+\.?\d*)", text, re.IGNORECASE)
        if match:
            return float(match.group(1))
        return 999.0 
    return sorted(items, key=extract_unit_number)

# --- UPDATED: THE BULLETPROOF CALL_OLLAMA WITH JSON SCRUBBER ---
def call_ollama(prompt):
    url = "http://localhost:11434/api/generate"
    try:
        # 120s timeout is critical for full subject generation
        response = requests.post(url, json={"model": "llama3", "prompt": prompt, "stream": False, "format": "json"}, timeout=120)
        raw_response = response.json().get("response", "")
        
        # THE JSON SCRUBBER: This finds the JSON block even if the AI is "chatty"
        # It looks for the first '{' and the last '}'
        match = re.search(r'(\{.*\})', raw_response, re.DOTALL)
        if match:
            clean_json = match.group(1)
            return json.loads(clean_json)
        else:
            return json.loads(raw_response) # Fallback if regex fails
            
    except Exception as e:
        print(f"CRITICAL BACKEND ERROR: {str(e)}")
        return {"error": "AI failed to respond.", "is_in_syllabus": True, "content": "The AI engine is busy. Please try again in a moment."}

@app.post("/api/extract-text/")
async def extract_text(file: UploadFile = File(...)):
    content = await file.read()
    extracted_text = ""
    if file.filename.lower().endswith(".pdf"):
        pdf_reader = PyPDF2.PdfReader(io.BytesIO(content))
        for page in pdf_reader.pages:
            text = page.extract_text()
            if text: extracted_text += text + "\n"
    elif file.filename.lower().endswith(".txt"):
        extracted_text = content.decode("utf-8")
    return {"text": extracted_text}

# --- SYLLABUS GATEKEEPER (Loosened for Demo Stability) ---
@app.post("/api/generate-from-topic/")
async def generate_from_topic(request: TopicRequest):
    prompt = f"""
    You are an expert academic advisor for {request.university}.
    TASK: Provide exhaustive educational content for '{request.topic}' for a {request.year} {request.stream} student.
    
    GUIDELINE: Align with State Educational Policy (SEP) standards. 
    STABILITY RULE: Unless the topic is absolute gibberish, treat "is_in_syllabus" as true.
    
    Return ONLY valid JSON:
    {{
      "is_in_syllabus": true, 
      "content": "If the input is a SUBJECT, organize strictly by syllabus UNITS. For every Unit, list the TOPICS and then provide a massive, exhaustive, textbook-level deep-dive for each topic. If it is a narrow TOPIC, provide a massive high-detail explanation. Use 100% capacity."
    }}
    """
    return call_ollama(prompt)

@app.post("/api/generate-session/")
async def generate_session(request: StudyRequest):
    global session_errors
    
    if request.mode == "initial":
        session_errors = [] 
        text_length = len(request.content)
        
        # Dynamic Scaling
        if text_length < 1500: 
            q_count, kp_count = 5, 3
        elif text_length < 5000: 
            q_count, kp_count = 8, 6
        else: 
            q_count, kp_count = 12, 10
        
        json_template = {
            "summary": "...",
            "key_points": ["Unit 1: ..."] * kp_count,
            "imp_topics": ["Unit 1: ..."] * kp_count,
            "imp_questions": ["Unit 1: ..."] * (q_count // 2),
            "short_questions": ["Unit 1 (1-Mark): ..."] * q_count,
            "quiz": [{"question": "...", "options": ["A", "B", "C", "D"], "correct_answer": "...", "topic_tag": "..."}] * q_count
        }
        
        instructions = [
            "- 'summary': Comprehensive overview following Unit progression.",
            f"- 'key_points': EXACTLY {kp_count} points. Prefix each with its Unit (e.g., 'Unit 1: ...').",
            f"- 'imp_topics': EXACTLY {kp_count} sub-topics. Prefix each with its Unit.",
            f"- 'imp_questions': EXACTLY {q_count // 2} subjective questions. Prefix each with its Unit.",
            f"- 'short_questions': EXACTLY {q_count} objective items. Prefix with Unit and Mark (e.g., 'Unit 1 (1-Mark): ...').",
            f"- 'quiz': EXACTLY {q_count} MCQs pulling evenly from all Units."
        ]

        prompt = f"""
        TASK: Analyze notes inside <notes> tags. 
        <notes>{request.content[:10000]}</notes>

        Return ONLY valid JSON matching this template. Fill every slot:
        {json.dumps(json_template)}
        
        Rules: {chr(10).join(instructions)}
        """
        
        raw_data = call_ollama(prompt)
        
        # Apply the Sorting Layer to ensure Chronological Units
        for key in ["key_points", "imp_topics", "imp_questions", "short_questions"]:
            if key in raw_data and isinstance(raw_data[key], list):
                raw_data[key] = sort_by_unit(raw_data[key])
        
        return raw_data

    else:
        weak_topics = ", ".join(list(set(session_errors)))
        if not session_errors:
            prompt = f"TASK: Perfect score! Generate 1 advanced MCQ from these notes: {request.content[:5000]}. Return JSON: {{'remediation_notes': '...', 'targeted_quiz': [...]}}"
        else:
            prompt = f"TASK: Review weak topics: {weak_topics}. Use notes: {request.content[:5000]}. Return JSON: {{'remediation_notes': '...', 'targeted_quiz': [...]}}"
            
    return call_ollama(prompt)

@app.post("/api/track-error/")
async def track_error(request: FeedbackRequest):
    global session_errors
    if not request.is_correct: 
        if request.concept not in session_errors: session_errors.append(request.concept)
    else:
        if request.concept in session_errors: session_errors.remove(request.concept)
    return {"status": "tracked", "remaining_weak_spots": len(session_errors)}