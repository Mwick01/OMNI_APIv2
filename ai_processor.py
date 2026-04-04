import os
import json
import base64
import fitz  # PyMuPDF
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

# Initialize OpenAI
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

def analyze_notice(title, filepath, file_type):
    """Uses ChatGPT to extract course name, deadlines, and a summary from Text or Images."""
    
    title_lower = title.lower()
    # 1. Filter out Exam Centers immediately
    if any(keyword in title_lower for keyword in ["exam center", "exam centre", "examination center", "examination centre"]):
        return {
            "is_exam_center": True,
            "course_name": None,
            "deadline": None,
            "summary": "This is an examination center allocation notice."
        }

    # 2. Build the strict prompt
    prompt_text = f"""
        You are an assistant for a university in Sri Lanka. Analyze this notice carefully.
        Notice Title: {title}

        Instructions:
        1. This is a university exam results sheet. Extract the following fields:
        - "subject_code": The specific subject/module code shown (e.g., "MSF2223", "CSC1234", "PHY1234"). 
            This is usually a short alphanumeric code like "MSF2223". Look carefully in the header area.
        - "subject_name": The specific subject/module name (e.g., "Numerical Analysis II", "Data Structures").
            This is different from the degree programme name.
        - "degree_programme": The broader degree programme (e.g., "Financial Mathematics and Industrial Statistics").
        - "semester_exam": The semester/exam session if mentioned (e.g., "Level II Semester II 2023/2024").
        - "deadline": Any explicit deadline or important date. If none, return null.
        - "summary": A 1-2 sentence summary. Do not include greetings.

        2. Do NOT confuse the degree programme name with the subject name.
        Example: Degree = "Financial Mathematics and Industrial Statistics", Subject = "Numerical Analysis II (MSF2223)"

        Return STRICTLY in this JSON format without markdown or extra text:
        {{
            "subject_code": "MSF2223",
            "subject_name": "Numerical Analysis II",
            "degree_programme": "Financial Mathematics and Industrial Statistics",
            "semester_exam": "Level II Semester II Examination 2023/2024",
            "deadline": null,
            "summary": "Short summary here"
        }}
        """

    messages = [{"role": "user", "content": []}]

    # 3. Handle PDF (Convert to Image) vs TXT
    if file_type == "pdf":
        try:
            # Grab the first page and turn it into an image in memory
            doc = fitz.open(filepath)
            page = doc.load_page(0)
            pix = page.get_pixmap(dpi=150)
            img_data = pix.tobytes("png")
            base64_image = base64.b64encode(img_data).decode('utf-8')
            doc.close()

            # Attach text instructions AND the image to the message
            messages[0]["content"].append({"type": "text", "text": prompt_text})
            messages[0]["content"].append({
                "type": "image_url",
                "image_url": {"url": f"data:image/png;base64,{base64_image}", "detail": "high"}
            })
        except Exception as e:
            print(f"PDF Image Conversion Error: {e}")
            return None
            
    elif file_type == "txt":
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                file_text = f.read()
            full_prompt = prompt_text + f"\n\nNotice Content:\n{file_text}"
            messages[0]["content"].append({"type": "text", "text": full_prompt})
        except Exception as e:
            print(f"Text Read Error: {e}")
            return None
    else:
        return None # Unsupported file type

    # 4. Send to ChatGPT
    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            temperature=0.2,
            messages=messages
        )
        
        raw_content = response.choices[0].message.content.strip()
        
        # Clean up JSON formatting if GPT adds markdown blocks
        if raw_content.startswith("```json"):
            raw_content = raw_content[7:-3]
        elif raw_content.startswith("```"):
            raw_content = raw_content[3:-3]
            
        ai_data = json.loads(raw_content)
        ai_data["is_exam_center"] = False
        return ai_data
        
    except Exception as e:
        print(f"OpenAI Error: {e}")
        return None