from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import PyPDF2, io, requests, json

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
    Evaluate if '{request.topic}' is realistically part of the standard curriculum for a {request.year} student studying {request.stream}.
    
    Return ONLY valid JSON matching this exact structure:
    {{
      "is_in_syllabus": true, 
      "content": "If true, determine if '{request.topic}' is a broad SUBJECT (like 'Operating Systems') or a narrow TOPIC. CRITICAL INSTRUCTION: If it is a full SUBJECT, you MUST organize the response by syllabus UNITS (e.g., Unit 1, Unit 2). For EVERY single Unit, you must first explicitly list the core TOPICS contained in that unit, and then provide a massive, exhaustive, textbook-level deep-dive explaining every single topic to its fullest capacity. Include technical definitions, core principles, and examples. Leave no sub-topic unexplained. If it is a narrow TOPIC, provide the same exhaustive deep-dive into just that concept. If false, write a polite 2-sentence explanation of why."
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
        
        # --- PYTHON CALCULATOR ---
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
        
        # --- SMART PREFIXING IMPLEMENTED BELOW ---
        if "summary" in request.preferences:
            instructions.append("- 'summary': A comprehensive overview of the text. If the text contains distinct Units, briefly summarize what each Unit covers.")
            json_template["summary"] = "..."
            
        if "key_points" in request.preferences:
            instructions.append(f"- 'key_points': A list of EXACTLY {kp_count} important takeaways. CRITICAL RULE: You MUST prefix every single point with its specific Unit from the notes (e.g., 'Unit 1: [Takeaway]'). Ensure items are distributed evenly across all Units. If no units exist, use 'General:'.")
            json_template["key_points"] = ["Unit 1: ..."] * kp_count
            
        if "imp_topics" in request.preferences:
            instructions.append(f"- 'imp_topics': A list of EXACTLY {kp_count} highly important sub-topics. CRITICAL RULE: You MUST prefix every single topic with its specific Unit (e.g., 'Unit 1: [Topic]').")
            json_template["imp_topics"] = ["Unit 1: ..."] * kp_count
            
        if "imp_questions" in request.preferences:
            instructions.append(f"- 'imp_questions': A list of EXACTLY {q_count // 2} subjective questions for exam prep. CRITICAL RULE: You MUST prefix every single question with its specific Unit (e.g., 'Unit 1: [Question]').")
            json_template["imp_questions"] = ["Unit 1: ..."] * (q_count // 2)
            
        if "short_questions" in request.preferences:
            instructions.append(f"- 'short_questions': A combined list of EXACTLY {q_count} short objective questions. CRITICAL RULE: You MUST prefix each with the unit AND the mark (e.g., 'Unit 1 (1-Mark): [Question]' or 'Unit 2 (2-Mark): [Question]').")
            json_template["short_questions"] = ["Unit 1 (1-Mark): ..."] * q_count

        if "quiz" in request.preferences:
            instructions.append(f"- 'quiz': A list of EXACTLY {q_count} multiple-choice questions. Ensure the questions pull evenly from all Units provided in the text.")
            quiz_obj = {"question": "...", "options": ["Option A", "Option B", "Option C", "Option D"], "correct_answer": "Exact text of the correct option", "topic_tag": "..."}
            json_template["quiz"] = [quiz_obj] * q_count 

        prompt = f"""
        TASK: You are an expert academic tutor. Analyze the STUDENT NOTES provided inside the <notes> tags below.
        
        <notes>
        {request.content[:10000]}
        </notes>

        Based EXCLUSIVELY on the STUDENT NOTES inside the tags above, fulfill these requirements:
        {chr(10).join(instructions)}
        
        CRITICAL INSTRUCTION: You MUST fill out every single item array in the JSON template below. Do not skip any slots. Follow the prefixing rules exactly.
        Return ONLY valid JSON matching this exact structure:
        {json.dumps(json_template)}
        """
    else:
        weak_topics = ", ".join(list(set(session_errors)))
        
        if not session_errors:
            prompt = f"""
            TASK: The student answered all previous questions correctly. Generate 1 highly advanced, difficult multiple-choice question based on the STUDENT NOTES provided below to test their ultimate mastery.
            
            <notes>
            {request.content[:10000]}
            </notes>

            Return ONLY valid JSON matching this exact structure. Replace the placeholder text with your generated advanced question and options:
            {{
              "remediation_notes": "Congratulations on getting a perfect score! Here is a final advanced challenge to test your absolute mastery.", 
              "targeted_quiz": [
                {{
                  "question": "ADVANCED: [Write a difficult question here]", 
                  "options": ["[Option A]", "[Option B]", "[Option C]", "[Option D]"], 
                  "correct_answer": "[Exact text of the correct option]", 
                  "topic_tag": "advanced"
                }}
              ]
            }}
            """
        else:
            prompt = f"""
            TASK: The student struggled with the following topics: {weak_topics}. 
            Generate a targeted review session based on the STUDENT NOTES provided below.
            
            <notes>
            {request.content[:10000]}
            </notes>

            Return ONLY valid JSON matching this exact structure. Replace the placeholder text with your generated content:
            {{
              "remediation_notes": "[Write a 3-sentence deep-dive explanation specifically addressing the weak topics: {weak_topics}]", 
              "targeted_quiz": [
                {{
                  "question": "[Write a new question specifically about {weak_topics}]", 
                  "options": ["[Option A]", "[Option B]", "[Option C]", "[Option D]"], 
                  "correct_answer": "[Exact text of the correct option]", 
                  "topic_tag": "remedial"
                }}
              ]
            }}
            """
            
    return call_ollama(prompt)

@app.post("/api/track-error/")
async def track_error(request: FeedbackRequest):
    global session_errors
    
    if not request.is_correct: 
        if request.concept not in session_errors:
            session_errors.append(request.concept)
    else:
        if request.concept in session_errors:
            session_errors.remove(request.concept)
            
    return {"status": "tracked", "remaining_weak_spots": len(session_errors)}