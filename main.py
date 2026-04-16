from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import PyPDF2, io, requests, json, re

app = FastAPI()

# Allow frontend to communicate with backend
app.add_middleware(
    CORSMiddleware, 
    allow_origins=["*"], 
    allow_methods=["*"], 
    allow_headers=["*"]
)

session_errors = []

# --- MODELS ---
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

# --- HELPERS ---

def call_ollama(prompt):
    """Sends prompt to Llama 3 with JSON scrubbing and timeout protection."""
    url = "http://localhost:11434/api/generate"
    try:
        # 120s timeout ensures the GPU has enough time for deep-dives
        response = requests.post(
            url, 
            json={"model": "llama3", "prompt": prompt, "stream": False, "format": "json"}, 
            timeout=120
        )
        raw_response = response.json().get("response", "")
        
        # THE JSON SCRUBBER: Extracts only the valid JSON block
        match = re.search(r'(\{.*\})', raw_response, re.DOTALL)
        if match:
            return json.loads(match.group(1))
        return json.loads(raw_response)
            
    except Exception as e:
        print(f"Ollama Error: {str(e)}")
        return {"error": "Inference Timeout", "is_in_syllabus": True, "content": "AI is busy or taking too long. Please try a more specific topic."}

# --- ENDPOINTS ---

@app.post("/api/extract-text/")
async def extract_text(file: UploadFile = File(...)):
    """Handles PDF and TXT file parsing."""
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

@app.post("/api/generate-from-topic/")
async def generate_from_topic(request: TopicRequest):
    """Concept Specialist: Deep-dives into topics while rejecting broad subjects."""
    prompt = f"""
    You are an expert academic tutor for {request.university}.
    
    TASK: Evaluate if '{request.topic}' is a broad full SUBJECT (e.g., 'Operating Systems', 'DBMS') 
    or a narrow, specific TOPIC/CONCEPT (e.g., 'Deadlock Prevention', 'Normalization').
    
    FILTRATION RULE:
    1. If broad SUBJECT: Set "is_in_syllabus" to false.
    2. If specific TOPIC: Set "is_in_syllabus" to true.

    Return ONLY valid JSON:
    {{
      "is_in_syllabus": true, 
      "content": "If true, provide a massive, exhaustive deep-dive description of '{request.topic}' including formal definitions, technical principles, and examples. If false, write: 'This appears to be a full subject. Please enter a specific concept (e.g., instead of {request.topic}, try a specific unit topic) for a deep-dive analysis.'"
    }}
    """
    return call_ollama(prompt)

@app.post("/api/generate-session/")
async def generate_session(request: StudyRequest):
    """Main engine for generating study guides and interactive quizzes."""
    global session_errors
    
    if request.mode == "initial":
        session_errors = [] 
        text_length = len(request.content)
        
        # --- DYNAMIC SCALING LOGIC FOR HIGHER DENSITY ---
        if text_length < 1500: 
            q_count, kp_count = 5, 3
            imp_topics_count = 6     
            imp_questions_count = 5  
        elif text_length < 5000: 
            q_count, kp_count = 8, 6
            imp_topics_count = 12    
            imp_questions_count = 10 
        else: 
            q_count, kp_count = 12, 10
            imp_topics_count = 18    
            imp_questions_count = 15 
        
        # Removed "Unit 1:" from the template placeholders
        json_template = {
            "summary": "...",
            "key_points": ["..."] * kp_count,
            "imp_topics": ["..."] * imp_topics_count,
            "imp_questions": ["..."] * imp_questions_count,
            "short_questions": ["(1-Mark): ..."] * q_count,
            "quiz": [{"question": "...", "options": ["A", "B", "C", "D"], "correct_answer": "...", "topic_tag": "..."}] * q_count
        }
        
        # Removed "Prefix each with its Unit" from instructions
        instructions = [
            f"- 'key_points': EXACTLY {kp_count} critical takeaways.",
            f"- 'imp_topics': EXACTLY {imp_topics_count} sub-topics. Do not just list the name; include a 2-sentence highly technical summary of WHY it is important.",
            f"- 'imp_questions': EXACTLY {imp_questions_count} tough, analytical, university-level subjective questions.",
            f"- 'short_questions': EXACTLY {q_count} items prefixed with the Mark (e.g., '(1-Mark): ...' or '(2-Mark): ...').",
            f"- 'quiz': EXACTLY {q_count} MCQs based exclusively on the provided text."
        ]

        prompt = f"""
        TASK: Analyze notes inside <notes> tags. 
        <notes>{request.content[:10000]}</notes>

        Return ONLY valid JSON. Fill every slot: {json.dumps(json_template)}
        Rules: {chr(10).join(instructions)}
        """
        
        return call_ollama(prompt)

    else:
        # Adaptive Remediation Logic
        weak_topics = ", ".join(list(set(session_errors)))
        if not session_errors:
            prompt = f"TASK: Perfect score! Generate 1 advanced question from: {request.content[:5000]}. Return JSON with 'remediation_notes' and 'targeted_quiz'."
        else:
            prompt = f"TASK: Review weak topics: {weak_topics}. Use notes: {request.content[:5000]}. Return JSON with 'remediation_notes' and 'targeted_quiz'."
            
    return call_ollama(prompt)

@app.post("/api/track-error/")
async def track_error(request: FeedbackRequest):
    """Tracks and removes weak concepts for the Adaptive Review loop."""
    global session_errors
    if not request.is_correct: 
        if request.concept not in session_errors: session_errors.append(request.concept)
    else:
        if request.concept in session_errors: session_errors.remove(request.concept)
    return {"status": "tracked", "remaining_weak_spots": len(session_errors)}