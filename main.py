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

# --- Syllabus Validation & MAXIMUM DATA Endpoint ---
@app.post("/api/generate-from-topic/")
async def generate_from_topic(request: TopicRequest):
    url = "http://localhost:11434/api/generate"
    
    prompt = f"""
    You are an expert academic advisor for {request.university}.
    Evaluate if the topic '{request.topic}' is realistically part of the standard curriculum for a {request.year} student studying {request.stream}.
    
    Return ONLY valid JSON matching this exact structure:
    {{
      "is_in_syllabus": true, // set to false if the topic strongly does not belong in this stream/year
      "content": "If true, generate the most exhaustive, comprehensive, and highly detailed study guide possible. Include a deep-dive introduction, core technical principles, real-world industry applications, relevant formulas/code examples (if applicable), and advanced edge cases. Do not hold back on detail—provide as much academic data as possible tailored to their exact level. If false, write a polite 2-sentence explanation of why this topic is not in their syllabus."
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
        
        json_template = {}
        instructions = []
        
        if "summary" in request.preferences:
            instructions.append("- 'summary': A solid 2-sentence overview.")
            json_template["summary"] = "..."
        if "key_points" in request.preferences:
            instructions.append("- 'key_points': A list of the 3 most important takeaways.")
            json_template["key_points"] = ["...", "...", "..."]
        if "imp_topics" in request.preferences:
            instructions.append("- 'imp_topics': A list of 3 highly important sub-topics the student should study.")
            json_template["imp_topics"] = ["...", "...", "..."]
        if "imp_questions" in request.preferences:
            instructions.append("- 'imp_questions': A list of 2 short-answer/subjective questions for exam prep.")
            json_template["imp_questions"] = ["...", "..."]
        if "quiz" in request.preferences:
            instructions.append("- 'quiz': A list of EXACTLY 5 multiple-choice questions ('question', 'options', 'correct_answer', 'topic_tag').")
            json_template["quiz"] = [{"question": "...", "options": ["Option 1 text", "Option 2 text", "Option 3 text", "Option 4 text"], "correct_answer": "Exact text of the correct option", "topic_tag": "..."}]

        # FIXED: Increased content limit from [:2000] to [:10000] to handle the massive new data
        prompt = f"""
        TASK: You are an expert academic tutor. Analyze the STUDENT NOTES provided inside the <notes> tags below.
        
        <notes>
        {request.content[:10000]}
        </notes>

        Based EXCLUSIVELY on the STUDENT NOTES inside the tags above, fulfill these requirements:
        {chr(10).join(instructions)}
        
        CRITICAL INSTRUCTION: Do not summarize or mention these instructions. Summarize ONLY the actual educational content inside the <notes> tags.
        Return ONLY valid JSON matching this exact structure. Ensure correct_answer contains the exact string of the correct option:
        {json.dumps(json_template)}
        """
    else:
        weak_topics = ", ".join(list(set(session_errors)))
        if not session_errors:
            prompt = f"""
            The student got everything right! Return ONLY valid JSON: 
            {{
              "remediation_notes": "Congratulations!", 
              "targeted_quiz": [
                {{
                  "question": "ADVANCED: ...", 
                  "options": ["Option 1 text", "Option 2 text", "Option 3 text", "Option 4 text"], 
                  "correct_answer": "Exact text of the correct option", 
                  "topic_tag": "advanced"
                }}
              ]
            }}
            """
        else:
            prompt = f"""
            Target weak topics: {weak_topics}. Using the student notes provided earlier.
            Return ONLY valid JSON: 
            {{
              "remediation_notes": "Deep-dive of {weak_topics}.", 
              "targeted_quiz": [
                {{
                  "question": "...", 
                  "options": ["Option 1 text", "Option 2 text", "Option 3 text", "Option 4 text"], 
                  "correct_answer": "Exact text of the correct option", 
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