import { useState } from 'react'
import axios from 'axios'

function App() {
  // --- 1. STATE MANAGEMENT ---
  const [currentStep, setCurrentStep] = useState('selection')
  const [inputType, setInputType] = useState(null)
  const [inputText, setInputText] = useState('')
  const [selectedFile, setSelectedFile] = useState(null)
  const [topic, setTopic] = useState('')
  
  // SEP Personalization State
  const [topicStream, setTopicStream] = useState('BCA')
  const [topicYear, setTopicYear] = useState('2nd Year')
  const [topicUni, setTopicUni] = useState('BCU')

  const [preferences, setPreferences] = useState({
    summary: true,
    key_points: false,
    imp_topics: false,
    imp_questions: false,
    short_questions: false,
    quiz: true
  })

  const [loading, setLoading] = useState(false)
  const [loadingMessage, setLoadingMessage] = useState('Processing...')
  const [sessionData, setSessionData] = useState(null)
  const [answeredCount, setAnsweredCount] = useState(0)
  const [selectedAnswer, setSelectedAnswer] = useState(null)
  const [isAnswerRevealed, setIsAnswerRevealed] = useState(false)
  const [weakTopics, setWeakTopics] = useState([])
  
  // Adaptive Loop State
  const [adaptiveAnsweredCount, setAdaptiveAnsweredCount] = useState(0)
  const [adaptiveSelectedAnswer, setAdaptiveSelectedAnswer] = useState(null)
  const [adaptiveIsAnswerRevealed, setAdaptiveIsAnswerRevealed] = useState(false)

  // --- 2. LOGIC HANDLERS ---

  const handleToggle = (key) => {
    setPreferences(prev => ({ ...prev, [key]: !prev[key] }))
  }

  const handleStartProcess = async () => {
    const selectedPrefs = Object.keys(preferences).filter(k => preferences[k]);
    if (selectedPrefs.length === 0) return alert("Please select at least one output type!");

    setLoading(true);
    let finalRawText = "";

    try {
      if (inputType === 'text') {
        if (!inputText) return alert("Please paste some text.");
        finalRawText = inputText;
      } else if (inputType === 'pdf') {
        if (!selectedFile) return alert("Please select a file.");
        setLoadingMessage("Extracting text from PDF...");
        const formData = new FormData(); 
        formData.append('file', selectedFile);
        const res = await axios.post('http://127.0.0.1:8000/api/extract-text/', formData);
        finalRawText = res.data.text;
      } else if (inputType === 'topic') {
        if (!topic) return alert("Please enter a concept.");
        setLoadingMessage("Auditing syllabus relevance (SEP)...");

        const res = await axios.post('http://127.0.0.1:8000/api/generate-from-topic/', {
          topic: topic,
          stream: topicStream,
          year: topicYear,
          university: topicUni
        });

        console.log("RAW BACKEND RESPONSE:", res.data); // Crucial for Hackathon Debugging

        if (res.data.error) {
           alert(`Backend Error: ${res.data.content || "The AI Engine is busy or timed out."}`);
           setLoading(false);
           return;
        }

        // --- UPDATED ALERT: Covers both Wrong Syllabus AND Broad Subjects ---
        if (res.data.is_in_syllabus === false) {
          alert(`🚫 SYLLABUS AUDIT ALERT!\n\n${res.data.content}`);
          setLoading(false);
          return;
        }
        
        finalRawText = res.data.content;
      }

      // Safety check to prevent 422 error
      if (!finalRawText || typeof finalRawText !== 'string') {
        console.error("FAILED TEXT DATA:", finalRawText);
        alert("The AI generated an invalid format. Please press F12 and check the Console for details.");
        setLoading(false);
        return;
      }

      setInputText(finalRawText);
      setLoadingMessage("Customizing your Master Class...");

      const sessionRes = await axios.post('http://127.0.0.1:8000/api/generate-session/', {
        content: finalRawText,
        mode: 'initial',
        preferences: selectedPrefs
      });

      setSessionData(sessionRes.data);

      if (selectedPrefs.includes("quiz")) {
        setCurrentStep('quiz');
        setAnsweredCount(0);
        setSelectedAnswer(null);
        setIsAnswerRevealed(false);
        setWeakTopics([]);
      } else {
        setCurrentStep('results_only');
      }
    } catch (err) {
      console.error("AXIOS ERROR:", err.response ? err.response.data : err.message);
      alert("Error communicating with backend. Is your Python server running?");
    }
    setLoading(false);
  };

  const handleAnswerSubmit = async (selected, correct, topicTag) => {
    setSelectedAnswer(selected);
    setIsAnswerRevealed(true);
    const safeSelected = String(selected).trim().toLowerCase();
    const safeCorrect = String(correct).trim().toLowerCase();
    const isCorrect = safeSelected === safeCorrect || safeSelected.includes(safeCorrect) || safeCorrect.includes(safeSelected);

    if (!isCorrect) {
      setWeakTopics(prev => prev.includes(topicTag) ? prev : [...prev, topicTag]);
    }
    await axios.post('http://127.0.0.1:8000/api/track-error/', { concept: topicTag, is_correct: isCorrect });
  };

  const handleNextQuestion = () => {
    const nextCount = answeredCount + 1;
    if (nextCount >= sessionData.quiz.length) {
      setCurrentStep('decision');
    } else {
      setAnsweredCount(nextCount);
      setSelectedAnswer(null);
      setIsAnswerRevealed(false);
    }
  };

  const handleAdaptiveAnswerSubmit = async (selected, correct, topicTag) => {
    setAdaptiveSelectedAnswer(selected);
    setAdaptiveIsAnswerRevealed(true);
    const safeSelected = String(selected).trim().toLowerCase();
    const safeCorrect = String(correct).trim().toLowerCase();
    const isCorrect = safeSelected === safeCorrect || safeSelected.includes(safeCorrect) || safeCorrect.includes(safeSelected);

    if (isCorrect) {
      setWeakTopics(prev => prev.filter(t => t !== topicTag));
    } else {
      setWeakTopics(prev => prev.includes(topicTag) ? prev : [...prev, topicTag]);
    }
    await axios.post('http://127.0.0.1:8000/api/track-error/', { concept: topicTag, is_correct: isCorrect });
  };

  const handleNextAdaptiveQuestion = () => {
    setAdaptiveAnsweredCount(prev => prev + 1);
    setAdaptiveSelectedAnswer(null);
    setAdaptiveIsAnswerRevealed(false);
  };

  const startAdaptiveSession = async () => {
    setLoading(true);
    setLoadingMessage("Generating personalized review loop...");
    try {
      const res = await axios.post('http://127.0.0.1:8000/api/generate-session/', { 
        content: inputText, 
        mode: 'adaptive', 
        preferences: [] 
      });
      setSessionData(res.data);
      setCurrentStep('adaptive');
      setAdaptiveAnsweredCount(0);
      setAdaptiveSelectedAnswer(null);
      setAdaptiveIsAnswerRevealed(false);
    } catch (err) { alert("Error generating adaptive session."); }
    setLoading(false);
  };

  // --- 3. UI STYLES & HELPERS ---
  const ulStyle = { textAlign: 'left', paddingLeft: '40px', lineHeight: '1.6', fontSize: '1.1rem', color: '#333' };
  const pStyle = { textAlign: 'left', lineHeight: '1.6', fontSize: '1.1rem', color: '#333' };

  const RenderCustomOutputs = () => (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '15px', marginBottom: '20px' }}>
      {sessionData.summary && <div style={cardStyle}><h3>📖 Master Summary</h3><p style={pStyle}>{sessionData.summary}</p></div>}
      {sessionData.key_points && <div style={cardStyle}><h3>🔑 Core Principles</h3><ul style={ulStyle}>{sessionData.key_points.map((p, i) => <li key={i}>{p}</li>)}</ul></div>}
      {sessionData.imp_topics && <div style={cardStyle}><h3>📌 Critical Sub-Topics</h3><ul style={ulStyle}>{sessionData.imp_topics.map((p, i) => <li key={i}>{p}</li>)}</ul></div>}
      {sessionData.imp_questions && <div style={cardStyle}><h3>✍️ Analytical Exam Prep</h3><ul style={ulStyle}>{sessionData.imp_questions.map((p, i) => <li key={i}>{p}</li>)}</ul></div>}
      {sessionData.short_questions && <div style={cardStyle}><h3>🎯 Quick Recall Questions</h3><ul style={ulStyle}>{sessionData.short_questions.map((p, i) => <li key={i} style={{ marginBottom: '8px' }}>{p}</li>)}</ul></div>}
    </div>
  );

  return (
    <div style={{ padding: '40px', maxWidth: '900px', margin: '0 auto', fontFamily: 'sans-serif', color: '#333' }}>
      <h1 style={{ textAlign: 'center', color: '#007bff', fontWeight: 'bold' }}>🎓 Smart AI Tutor</h1>

      {currentStep === 'selection' && (
        <div style={{ textAlign: 'center', animation: 'fadeIn 0.5s' }}>
          <h2 style={{ color: '#007bff' }}>What do you want to learn today?</h2>
          <div style={{ display: 'flex', gap: '20px', justifyContent: 'center', marginTop: '30px' }}>
            <button onClick={() => { setInputType('text'); setCurrentStep('input'); }} style={btnStyle}>📝 Paste Notes</button>
            <button onClick={() => { setInputType('pdf'); setCurrentStep('input'); }} style={btnStyle}>📄 Upload PDF</button>
            <button onClick={() => { setInputType('topic'); setCurrentStep('input'); }} style={btnStyle}>💡 Specific Concept</button>
          </div>
        </div>
      )}

      {currentStep === 'input' && !loading && (
        <div style={{ background: '#f8f9fa', padding: '30px', borderRadius: '10px', animation: 'fadeIn 0.5s' }}>
          <button onClick={() => setCurrentStep('selection')} style={{ background: 'none', border: 'none', color: '#007bff', cursor: 'pointer', marginBottom: '20px', fontWeight: 'bold' }}>← Back</button>

          {inputType === 'text' && <textarea rows="6" style={{ width: '100%', padding: '15px', borderRadius: '8px', color: '#000', background: '#fff' }} placeholder="Paste your raw notes here..." onChange={(e) => setInputText(e.target.value)} />}
          {inputType === 'pdf' && <div style={{ padding: '40px', border: '2px dashed #ccc', textAlign: 'center', background: '#fff', color: '#000' }}><input type="file" accept=".pdf,.txt" onChange={(e) => setSelectedFile(e.target.files[0])} /></div>}

          {inputType === 'topic' && (
            <div style={{ animation: 'fadeIn 0.5s' }}>
              <h3 style={{ marginTop: 0, color: '#007bff' }}>What specific concept do you need help with?</h3>
              <input type="text" style={{ width: '100%', padding: '15px', fontSize: '1.2rem', borderRadius: '8px', border: '1px solid #ccc', marginBottom: '15px', color: '#000', background: '#fff' }} placeholder="e.g., Deadlock Prevention, Normalization..." onChange={(e) => setTopic(e.target.value)} />

              <h3 style={{ marginTop: '10px', color: '#007bff' }}>Syllabus Auditor (SEP Context):</h3>
              <div style={{ display: 'flex', gap: '15px', marginBottom: '20px' }}>
                <select style={dropdownStyle} value={topicStream} onChange={(e) => setTopicStream(e.target.value)}>
                  <option value="BCA">BCA</option>
                  <option value="BCom">BCom</option>
                  <option value="BSc">BSc</option>
                  <option value="BA">BA</option>
                  <option value="BTech">BTech</option>
                </select>
                <select style={dropdownStyle} value={topicYear} onChange={(e) => setTopicYear(e.target.value)}>
                  <option value="1st Year">1st Year</option>
                  <option value="2nd Year">2nd Year</option>
                  <option value="3rd Year">3rd Year</option>
                  <option value="4th Year">4th Year</option>
                </select>
                <select style={dropdownStyle} value={topicUni} onChange={(e) => setTopicUni(e.target.value)}>
                  <option value="BCU">BCU (Bengaluru City University)</option>
                  <option value="BU">BU (Bangalore University)</option>
                  <option value="VTU">VTU</option>
                  <option value="Other">Other University</option>
                </select>
              </div>
            </div>
          )}

          <div style={{ marginTop: '25px', padding: '20px', background: '#fff', borderRadius: '8px', border: '1px solid #ddd' }}>
            <h3 style={{ marginTop: 0, color: '#007bff' }}>Configure Master Class Output:</h3>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '10px' }}>
              {Object.keys(preferences).map(key => (
                <label key={key} style={{ display: 'flex', alignItems: 'center', cursor: 'pointer', padding: '10px', background: preferences[key] ? '#eef2ff' : '#f8f9fa', borderRadius: '5px', border: `1px solid ${preferences[key] ? '#b6d4fe' : '#ddd'}`, color: '#333' }}>
                  <input type="checkbox" checked={preferences[key]} onChange={() => handleToggle(key)} style={{ marginRight: '10px' }} />
                  {key.replace(/_/g, ' ').toUpperCase()}
                </label>
              ))}
            </div>
          </div>

          <button onClick={handleStartProcess} style={{ width: '100%', marginTop: '20px', padding: '15px', background: '#28a745', color: '#fff', border: 'none', borderRadius: '8px', cursor: 'pointer', fontSize: '1.1rem', fontWeight: 'bold' }}>
            Generate Custom Session
          </button>
        </div>
      )}

      {currentStep === 'results_only' && sessionData && !loading && (
        <div style={{ animation: 'fadeIn 0.5s' }}>
          <h2 style={{ color: '#007bff' }}>Your Master Class Materials</h2>
          <RenderCustomOutputs />
          <button onClick={() => { setCurrentStep('selection'); setInputType(null); }} style={{ padding: '15px 30px', background: '#007bff', color: 'white', border: 'none', borderRadius: '8px', cursor: 'pointer', display: 'block', margin: '0 auto', fontWeight: 'bold' }}>Start New Session</button>
        </div>
      )}

      {currentStep === 'quiz' && sessionData && !loading && (
        <div style={{ animation: 'fadeIn 0.5s' }}>
          <RenderCustomOutputs />
          <h3 style={{ borderTop: '2px solid #444', paddingTop: '20px', color: '#007bff' }}>
            Interactive Quiz (Question {answeredCount + 1} of {sessionData.quiz.length})
          </h3>
          <div style={{ background: '#fff', padding: '20px', border: '1px solid #eee', borderRadius: '10px', boxShadow: '0 4px 6px rgba(0,0,0,0.05)' }}>
            <p style={{ fontSize: '1.2rem', fontWeight: 'bold', color: '#111' }}>{sessionData.quiz[answeredCount].question}</p>
            {sessionData.quiz[answeredCount].options?.map((opt, i) => {
              const safeCorrect = String(sessionData.quiz[answeredCount].correct_answer).trim().toLowerCase();
              const safeOpt = String(opt).trim().toLowerCase();
              const isCorrectOpt = safeOpt === safeCorrect || safeOpt.includes(safeCorrect) || safeCorrect.includes(safeOpt);
              const isSelectedOpt = opt === selectedAnswer;
              let btnBg = '#f8f9fa'; let btnBorder = '#ddd'; let icon = '';
              if (isAnswerRevealed) {
                if (isCorrectOpt) { btnBg = '#d1e7dd'; btnBorder = '#198754'; icon = ' ✅'; }
                else if (isSelectedOpt && !isCorrectOpt) { btnBg = '#f8d7da'; btnBorder = '#dc3545'; icon = ' ❌'; }
              }
              return (
                <button key={i} disabled={isAnswerRevealed} onClick={() => handleAnswerSubmit(opt, sessionData.quiz[answeredCount].correct_answer, sessionData.quiz[answeredCount].topic_tag)}
                  style={{ display: 'block', width: '100%', margin: '10px 0', padding: '15px', textAlign: 'left', borderRadius: '8px', border: `2px solid ${btnBorder}`, cursor: isAnswerRevealed ? 'default' : 'pointer', background: btnBg, fontSize: '1rem', color: '#111', fontWeight: '500' }}>
                  {opt} {icon}
                </button>
              )
            })}
            {isAnswerRevealed && (
              <button onClick={handleNextQuestion} style={{ width: '100%', padding: '15px', background: '#007bff', color: 'white', border: 'none', borderRadius: '8px', cursor: 'pointer', fontSize: '1.1rem', fontWeight: 'bold', marginTop: '15px' }}>
                {answeredCount + 1 >= sessionData.quiz.length ? "Finish Quiz & See Results" : "Next Question ➔"}
              </button>
            )}
          </div>
        </div>
      )}

      {currentStep === 'decision' && !loading && (
        <div style={{ textAlign: 'center', padding: '50px', background: '#f0f4f8', borderRadius: '15px', animation: 'fadeIn 0.5s' }}>
          <h2 style={{ color: '#111' }}>Quiz Finished! 🏁</h2>
          {weakTopics.length > 0 ? (
            <div style={{ background: '#f8d7da', padding: '20px', borderRadius: '12px', border: '1px solid #f5c2c7', maxWidth: '500px', margin: '0 auto 30px auto', textAlign: 'left' }}>
              <h3 style={{ color: '#842029', marginTop: 0 }}>📊 Performance Analysis</h3>
              <ul style={{ color: '#842029' }}>{weakTopics.map((topic, index) => (<li key={index}>{topic.toUpperCase()}</li>))}</ul>
            </div>
          ) : (
            <div style={{ background: '#d1e7dd', padding: '20px', borderRadius: '12px', border: '1px solid #badbcc', maxWidth: '500px', margin: '0 auto 30px auto' }}>
              <h3 style={{ color: '#0f5132' }}>🏆 Flawless Victory!</h3>
            </div>
          )}
          <div style={{ display: 'flex', gap: '15px', justifyContent: 'center' }}>
            <button onClick={startAdaptiveSession} style={{ padding: '15px 30px', background: '#007bff', color: 'white', border: 'none', borderRadius: '8px', fontWeight: 'bold', cursor: 'pointer' }}>Start Adaptive Review 🚀</button>
            <button onClick={() => window.location.reload()} style={{ padding: '15px 30px', background: '#6c757d', color: 'white', border: 'none', borderRadius: '8px', cursor: 'pointer' }}>Quit Early</button>
          </div>
        </div>
      )}

      {currentStep === 'adaptive' && sessionData && !loading && (
        <div style={{ animation: 'fadeIn 0.5s' }}>
          <div style={{ background: '#fff3cd', padding: '25px', borderRadius: '12px', border: '1px solid #ffeeba', marginBottom: '20px' }}>
            <h2 style={{ color: '#856404', marginTop: 0 }}>🔥 Targeted Deep Dive</h2>
            <p style={{ color: '#856404' }}>{sessionData.remediation_notes}</p>
          </div>
          {sessionData.targeted_quiz && sessionData.targeted_quiz.length > 0 && adaptiveAnsweredCount < sessionData.targeted_quiz.length ? (
            <div style={{ background: '#fff', padding: '20px', border: '1px solid #eee', borderRadius: '10px' }}>
              <h3 style={{ color: '#007bff' }}>Mastery Check ({adaptiveAnsweredCount + 1} of {sessionData.targeted_quiz.length})</h3>
              <p style={{ fontWeight: 'bold', color: '#111' }}>{sessionData.targeted_quiz[adaptiveAnsweredCount].question}</p>
              {sessionData.targeted_quiz[adaptiveAnsweredCount].options?.map((opt, i) => {
                const isSelected = opt === adaptiveSelectedAnswer;
                let btnBg = '#f8f9fa';
                if (adaptiveIsAnswerRevealed && isSelected) btnBg = '#eef2ff';
                return (
                  <button key={i} disabled={adaptiveIsAnswerRevealed} onClick={() => handleAdaptiveAnswerSubmit(opt, sessionData.targeted_quiz[adaptiveAnsweredCount].correct_answer, sessionData.targeted_quiz[adaptiveAnsweredCount].topic_tag)}
                    style={{ display: 'block', width: '100%', margin: '10px 0', padding: '15px', textAlign: 'left', borderRadius: '8px', border: '2px solid #ddd', background: btnBg, color: '#111', cursor: adaptiveIsAnswerRevealed ? 'default' : 'pointer' }}>
                    {opt}
                  </button>
                )
              })}
              {adaptiveIsAnswerRevealed && <button onClick={handleNextAdaptiveQuestion} style={{ width: '100%', padding: '15px', background: '#007bff', color: 'white', border: 'none', borderRadius: '8px', marginTop: '15px', cursor: 'pointer', fontWeight: 'bold' }}>Next ➔</button>}
            </div>
          ) : (
            <div style={{ textAlign: 'center', padding: '40px', background: '#d1e7dd', borderRadius: '12px' }}>
              <h2 style={{ color: '#0f5132' }}>🏆 Total Mastery Achieved!</h2>
              <button onClick={() => window.location.reload()} style={{ padding: '15px 40px', background: '#198754', color: '#fff', border: 'none', borderRadius: '8px', fontWeight: 'bold', cursor: 'pointer' }}>Finish & Exit ➔</button>
            </div>
          )}
        </div>
      )}

      {loading && (
        <div style={{ textAlign: 'center', padding: '50px' }}>
          <h2 style={{ color: '#007bff' }}>🤖 {loadingMessage}</h2>
          <p style={{ color: '#666' }}>Processing on local AI cluster...</p>
        </div>
      )}
    </div>
  );
}

// --- 4. STYLES ---
const btnStyle = { flex: 1, padding: '25px', fontSize: '1.1rem', fontWeight: 'bold', background: '#fff', border: '2px solid #007bff', color: '#007bff', borderRadius: '12px', cursor: 'pointer', transition: 'all 0.2s' };
const cardStyle = { background: '#eef2ff', padding: '20px', borderRadius: '10px' };
const dropdownStyle = { flex: 1, padding: '12px', borderRadius: '8px', border: '1px solid #ccc', fontSize: '1rem', background: '#fff', color: '#000', cursor: 'pointer' };

export default App;