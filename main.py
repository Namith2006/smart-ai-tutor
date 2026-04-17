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
        return {"error": "Inference Timeout", "is_in_syllabus": True, "content": "AI is busy or taking too long. Please try a more specific concept."}

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
    """Strict Syllabus Auditor & Concept Specialist"""
    prompt = f"""
    You are a RUTHLESS academic syllabus auditor for {request.university}.
    
    TASK: Strictly evaluate if '{request.topic}' belongs in the syllabus for a {request.year} student studying {request.stream} under standard State Educational Policy (SEP).
    
    CRITICAL REJECTION RULES (NO EXCEPTIONS):
    1. CROSS-STREAM VIOLATION: If the topic belongs to Science/Tech (e.g., 'Organic Chemistry', 'Machine Learning') but the stream is non-technical (e.g., 'BA', 'BCom'), YOU MUST REJECT IT. Do not assume they are taking an elective. Set "is_in_syllabus" to false.
    2. BROAD SUBJECT VIOLATION: If the input is an entire course name (e.g., 'Operating Systems', 'History', 'Physics') rather than a specific sub-concept, YOU MUST REJECT IT. Set "is_in_syllabus" to false.
    
    Return ONLY valid JSON:
    {{
      "is_in_syllabus": true, 
      "content": "If true, provide a massive, exhaustive deep-dive description of '{request.topic}'. If false, explain the exact reason for rejection (e.g., 'Organic Chemistry is a core Science topic and is not covered in a standard BA syllabus.' or 'This is a broad subject. Please provide a specific concept.')."
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
        
        # --- DYNAMIC SCALING LOGIC ---
        # Dialed down slightly to maximize speed for the Hackathon Demo
        if text_length < 1500: 
            q_count, kp_count, imp_topics_count, imp_questions_count = 5, 3, 6, 5
        elif text_length < 5000: 
            q_count, kp_count, imp_topics_count, imp_questions_count = 8, 6, 10, 8
        else: 
            q_count, kp_count, imp_topics_count, imp_questions_count = 10, 8, 12, 10
        
        # --- NEW: DYNAMIC PROMPT BUILDER ---
        # This is the magic! It ONLY adds keys to the JSON if you checked the box in React.
        json_template = {}
        instructions = []

        if "summary" in request.preferences:
            json_template["summary"] = "..."
            instructions.append("- 'summary': A comprehensive overview of the material.")

        if "key_points" in request.preferences:
            json_template["key_points"] = ["..."] * kp_count
            instructions.append(f"- 'key_points': EXACTLY {kp_count} critical takeaways.")

        if "imp_topics" in request.preferences:
            json_template["imp_topics"] = ["..."] * imp_topics_count
            instructions.append(f"- 'imp_topics': EXACTLY {imp_topics_count} sub-topics. Do not just list the name; include a 2-sentence highly technical summary of WHY it is important.")

        if "imp_questions" in request.preferences:
            json_template["imp_questions"] = ["..."] * imp_questions_count
            instructions.append(f"- 'imp_questions': EXACTLY {imp_questions_count} tough, analytical, university-level subjective questions.")

        if "short_questions" in request.preferences:
            json_template["short_questions"] = ["(1-Mark): ..."] * q_count
            instructions.append(f"- 'short_questions': EXACTLY {q_count} items prefixed with the Mark (e.g., '(1-Mark): ...').")

        if "quiz" in request.preferences:
            json_template["quiz"] = [{"question": "...", "options": ["A", "B", "C", "D"], "correct_answer": "...", "topic_tag": "..."}] * q_count
            # This fixes the green/red grading bug by forcing Llama 3 to write the full answer:
            instructions.append(f"- 'quiz': EXACTLY {q_count} MCQs based exclusively on the provided text. The 'correct_answer' field MUST be the exact, full string of the correct option. Do NOT just write 'A' or 'B'.")

        prompt = f"""
        TASK: Analyze notes inside <notes> tags. 
        <notes>{request.content[:5000]}</notes>

        Return ONLY valid JSON. Fill every slot in this template: {json.dumps(json_template)}
        Rules: {chr(10).join(instructions)}
        """
        
        return call_ollama(prompt)

    else:
        # --- STRICT ADAPTIVE TEMPLATE ---
        adaptive_template = {
            "remediation_notes": "Provide a highly detailed 2-paragraph explanation specifically addressing the student's weak topics.",
            "targeted_quiz": [
                {
                    "question": "...", 
                    "options": ["A", "B", "C", "D"], 
                    "correct_answer": "...", 
                    "topic_tag": "..."
                }
            ] * 3 # Generate 3 new targeted questions
        }
        
        weak_topics = ", ".join(list(set(session_errors)))
        if not session_errors:
            prompt = f"""
            TASK: The student got a perfect score! Give them an advanced challenge based on these notes: <notes>{request.content[:5000]}</notes>. 
            Return ONLY valid JSON matching this template: {json.dumps(adaptive_template)}
            RULE: The 'correct_answer' MUST be the exact full string of the correct option. Do NOT just write 'A' or 'B'.
            """
        else:
            prompt = f"""
            TASK: The student failed questions related to these specific topics: {weak_topics}. 
            Using these notes: <notes>{request.content[:5000]}</notes>
            Return ONLY valid JSON matching this template: {json.dumps(adaptive_template)}
            RULE: The 'correct_answer' MUST be the exact full string of the correct option. Do NOT just write 'A' or 'B'.
            """
            
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