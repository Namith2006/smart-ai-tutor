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

# --- NEW: HELPER TO SORT UNITS NUMERICALLY ---
def sort_by_unit(items):
    def extract_unit_number(text):
        # Finds "Unit 1", "Unit 1.1", etc.
        match = re.search(r"Unit\s+(\d+\.?\d*)", text, re.IGNORECASE)
        if match:
            return float(match.group(1))
        return 999.0 # Move "General" or un-prefixed items to the end
    
    return sorted(items, key=extract_unit_number)

def call_ollama(prompt):
    url = "http://localhost:11434/api/generate"
    try:
        response = requests.post(url, json={"model": "llama3", "prompt": prompt, "stream": False, "format": "json"})
        return json.loads(response.json().get("response", ""))
    except Exception as e:
        return {"error": "AI failed to respond."}

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

@app.post("/api/generate-from-topic/")
async def generate_from_topic(request: TopicRequest):
    url = "http://localhost:11434/api/generate"
    
    prompt = f"""
    You are an expert academic advisor for {request.university}.
    CRITICAL CONSTRAINT: You must evaluate if '{request.topic}' is strictly aligned with the State Educational Policy (SEP) syllabus for a {request.year} student studying {request.stream}.
    
    Return ONLY valid JSON:
    {{
      "is_in_syllabus": true, 
      "content": "If true, determine if '{request.topic}' is a broad SUBJECT or a narrow TOPIC. If it is a full SUBJECT, you MUST organize the response by syllabus UNITS (e.g., Unit 1, Unit 2). For EVERY single Unit, you must first explicitly list the core TOPICS contained in that unit, and then provide a massive, exhaustive, textbook-level deep-dive explaining every single topic to its fullest capacity. If it is a narrow TOPIC, provide the same exhaustive deep-dive. If false, write a polite 2-sentence explanation stating that this topic is outside the scope of the State Educational Policy syllabus."
    }}
    """
    
    try:
        response = requests.post(url, json={"model": "llama3", "prompt": prompt, "stream": False, "format": "json"})
        return json.loads(response.json().get("response", "{}"))
    except Exception as e:
        return {"is_in_syllabus": True, "content": "Error communicating with AI."}

@app.post("/api/generate-session/")
async def generate_session(request: StudyRequest):
    global session_errors
    
    if request.mode == "initial":
        session_errors = [] 
        text_length = len(request.content)
        if text_length < 1500: 
            q_count = 5
            kp_count = 3
        elif text_length < 5000: 
            q_count = 8
            kp_count = 6
        else: 
            q_count = 12
            kp_count = 10
        
        json_template = {}
        instructions = []
        
        if "summary" in request.preferences:
            instructions.append("- 'summary': A comprehensive overview. If units exist, summarize the progression from Unit 1 to the end.")
            json_template["summary"] = "..."
            
        if "key_points" in request.preferences:
            instructions.append(f"- 'key_points': A list of EXACTLY {kp_count} important takeaways. You MUST prefix every point with its specific Unit (e.g., 'Unit 1: [Takeaway]'). Group points by unit.")
            json_template["key_points"] = ["Unit 1: ..."] * kp_count
            
        if "imp_topics" in request.preferences:
            instructions.append(f"- 'imp_topics': A list of EXACTLY {kp_count} sub-topics. You MUST prefix every topic with its specific Unit (e.g., 'Unit 1: [Topic]').")
            json_template["imp_topics"] = ["Unit 1: ..."] * kp_count
            
        if "imp_questions" in request.preferences:
            instructions.append(f"- 'imp_questions': A list of EXACTLY {q_count // 2} subjective questions. You MUST prefix every question with its specific Unit.")
            json_template["imp_questions"] = ["Unit 1: ..."] * (q_count // 2)
            
        if "short_questions" in request.preferences:
            instructions.append(f"- 'short_questions': A list of EXACTLY {q_count} objective questions. Prefix with unit and mark (e.g., 'Unit 1 (1-Mark): ...').")
            json_template["short_questions"] = ["Unit 1 (1-Mark): ..."] * q_count

        if "quiz" in request.preferences:
            instructions.append(f"- 'quiz': A list of EXACTLY {q_count} MCQs pulling evenly from all Units.")
            quiz_obj = {"question": "...", "options": ["A", "B", "C", "D"], "correct_answer": "...", "topic_tag": "..."}
            json_template["quiz"] = [quiz_obj] * q_count 

        prompt = f"""
        TASK: Analyze the STUDENT NOTES inside the <notes> tags. 
        <notes>{request.content[:10000]}</notes>

        Fulfill these requirements in chronological order by Unit:
        {chr(10).join(instructions)}
        
        Return ONLY valid JSON. Ensure every array slot is filled.
        {json.dumps(json_template)}
        """
        
        raw_data = call_ollama(prompt)
        
        # --- APPLY THE SORTING LAYER ---
        for key in ["key_points", "imp_topics", "imp_questions", "short_questions"]:
            if key in raw_data and isinstance(raw_data[key], list):
                raw_data[key] = sort_by_unit(raw_data[key])
        
        return raw_data

    else:
        weak_topics = ", ".join(list(set(session_errors)))
        if not session_errors:
            prompt = f"TASK: Perfect score! Generate 1 advanced question from these notes: {request.content[:5000]}. Return JSON: {{'remediation_notes': '...', 'targeted_quiz': [...]}}"
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