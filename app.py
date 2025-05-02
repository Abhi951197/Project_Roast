# app.py - Flask Backend for Project Roast

from flask import Flask, request, jsonify
from flask_cors import CORS
import requests
import base64
import re
import os
import google.generativeai as genai
import random

app = Flask(__name__)
CORS(app)  # Enable CORS for all routes

# Configure API keys (in production, use environment variables)
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "your_github_token")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "your_gemini_api_key")

# Initialize Gemini client
genai.configure(api_key=GEMINI_API_KEY)

# Headers for GitHub API
headers = {
    "Authorization": f"token {GITHUB_TOKEN}",
    "Accept": "application/vnd.github.v3+json"
}

@app.route("/api/roast", methods=["POST"])
def roast_project():
    data = request.json
    repo_url = data.get("repoUrl")
    
    if not repo_url:
        return jsonify({"error": "No repository URL provided"}), 400
    
    try:
        # Extract owner and repo name from GitHub URL
        match = re.search(r"github\.com/([^/]+)/([^/]+)", repo_url)
        if not match:
            return jsonify({"error": "Invalid GitHub URL"}), 400
        
        owner, repo = match.groups()
        
        # Fetch repository details
        repo_info = fetch_repo_info(owner, repo)
        readme_content = fetch_readme(owner, repo)
        languages = fetch_languages(owner, repo)
        file_structure = fetch_file_structure(owner, repo)
        
        # Analyze the project
        analysis = analyze_project(repo_info, readme_content, languages, file_structure)
        
        # Generate a roast in Hinglish
        roast = generate_roast(analysis)
        
        return jsonify({
            "repoName": repo_info.get("name", "Unknown"),
            "repoOwner": owner,
            "repoDescription": repo_info.get("description", "No description available"),
            "repoStars": repo_info.get("stargazers_count", 0),
            "repoForks": repo_info.get("forks_count", 0),
            "languages": languages,
            "roast": roast
        })
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500

def fetch_repo_info(owner, repo):
    """Fetch basic repository information"""
    response = requests.get(f"https://api.github.com/repos/{owner}/{repo}", headers=headers)
    response.raise_for_status()
    return response.json()

def fetch_readme(owner, repo):
    """Fetch and decode README content"""
    try:
        response = requests.get(f"https://api.github.com/repos/{owner}/{repo}/readme", headers=headers)
        response.raise_for_status()
        content = response.json().get("content", "")
        if content:
            return base64.b64decode(content).decode("utf-8")
        return ""
    except:
        return "No README found"

def fetch_languages(owner, repo):
    """Fetch programming languages used in the repository"""
    response = requests.get(f"https://api.github.com/repos/{owner}/{repo}/languages", headers=headers)
    response.raise_for_status()
    return response.json()

def fetch_file_structure(owner, repo, path=""):
    """Recursively fetch file structure (limited to root level for performance)"""
    response = requests.get(f"https://api.github.com/repos/{owner}/{repo}/contents/{path}", headers=headers)
    response.raise_for_status()
    
    files = []
    for item in response.json():
        if item["type"] == "file":
            files.append(item["path"])
        # For performance reasons, we're only getting the root level files
        # If you want the complete structure, uncomment this code:
        # elif item["type"] == "dir":
        #     files.extend(fetch_file_structure(owner, repo, item["path"]))
    
    return files

def analyze_project(repo_info, readme, languages, file_structure):
    """Analyze the project structure and details"""
    # Calculate code complexity (simplified)
    complexity = "simple" if len(file_structure) < 10 else "complex" if len(file_structure) > 50 else "moderate"
    
    # Determine main language
    main_language = max(languages.items(), key=lambda x: x[1])[0] if languages else "Unknown"
    
    # Check for frameworks based on file structure
    frameworks = []
    if any("package.json" in file for file in file_structure):
        frameworks.append("Node.js")
    if any("requirements.txt" in file for file in file_structure):
        frameworks.append("Python")
    if any(file.endswith(".jsx") or file.endswith(".tsx") for file in file_structure):
        frameworks.append("React")
    
    # Extract project purpose from readme
    purpose = "Unknown purpose"
    if readme:
        # Simple extraction of first paragraph as purpose (in production, use a more sophisticated approach)
        first_paragraph = re.search(r"^#\s+(.+?)(?=\n\n|\n#|\Z)", readme)
        if first_paragraph:
            purpose = first_paragraph.group(1)
    
    return {
        "name": repo_info.get("name", ""),
        "stars": repo_info.get("stargazers_count", 0),
        "forks": repo_info.get("forks_count", 0),
        "description": repo_info.get("description", ""),
        "complexity": complexity,
        "main_language": main_language,
        "languages": list(languages.keys()),
        "frameworks": frameworks,
        "file_count": len(file_structure),
        "purpose": purpose
    }

def generate_roast(analysis):
    """Generate a humorous roast in Hinglish based on project analysis using Gemini"""
    try:
        prompt = f"""
        Generate a funny, lighthearted roast in Hinglish (mix of Hindi and English) for a GitHub project with these details:
        
        Project name: {analysis['name']}
        Description: {analysis['description']}
        Main language: {analysis['main_language']}
        All languages: {', '.join(analysis['languages'])}
        Frameworks: {', '.join(analysis['frameworks']) if analysis['frameworks'] else 'None detected'}
        Complexity: {analysis['complexity']}
        Stars: {analysis['stars']}
        Forks: {analysis['forks']}
        File count: {analysis['file_count']}
        
        Make it funny, mix Hindi and English words, use some tech jokes, but keep it high level can use cheap words also like chutiya , pagal .
        The roast should be 10-12 sentences, not too long. Use Hindi written in English letters (transliteration).
        """
        
        # Configure the Gemini model
        generation_config = {
            "temperature": 0.9,
            "top_p": 1,
            "top_k": 32,
            "max_output_tokens": 200,
        }
        
        # Use Gemini Pro model
        model = genai.GenerativeModel(
            model_name="gemini-pro",
            generation_config=generation_config
        )
        
        # Get response from Gemini
        response = model.generate_content([
            {
                "role": "user", 
                "parts": [{"text": "You are a funny tech critic who creates amusing roasts in Hinglish."}]
            },
            {
                "role": "model", 
                "parts": [{"text": "I'll create funny tech roasts in Hinglish, mixing Hindi and English words."}]
            },
            {
                "role": "user", 
                "parts": [{"text": prompt}]
            }
        ])
        
        return response.text.strip()
        
    except Exception as e:
        # Log the error for debugging
        print(f"Gemini API Error: {str(e)}")
        # Fallback to template-based roasts if API call fails
        return generate_fallback_roast(analysis)

def generate_fallback_roast(analysis):
    """Generate a fallback roast using templates if API call fails"""
    templates = [
        "Arre bhai {name}, yeh kya banaya hai? {main_language} mein itna {complexity} code, lagta hai aap {stars} stars ke saath bhi Stack Overflow se code copy karte ho!",
        "Yaar {name}, {main_language} use karke {file_count} files? Itna sab kuch sirf {description} ke liye? Thoda simple nahi bana sakte the? Chai peene mein jitna time lagta hai, usse jyada time iss repo ko samajhne mein lagega!",
        "Beta {name}, {main_language} seekh to liya, lekin documentation likhna bhool gaye kya? {stars} stars mile hain, par {forks} forks se lagta hai koi samajh hi nahi paya aapka code!",
        "Arey {name}, {main_language} ka use karke {complexity} project banaya hai? Waah! Par itna complex banane ki kya zaroorat thi? Lagta hai aapne interview ke liye GitHub profile impress karne ke chakkar mein over-engineering kar di!"
    ]
    
    template = random.choice(templates)
    return template.format(**{k: v for k, v in analysis.items() if isinstance(v, (str, int, float))})

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)