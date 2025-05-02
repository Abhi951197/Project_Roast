# app.py - Flask Backend for Project Roast

from flask import Flask, request, jsonify
from flask_cors import CORS
import requests
import base64
import re
import os
import google.generativeai as genai
import random
import time

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
        file_structure = fetch_file_structure(owner, repo)
        
        # Fetch and analyze actual code files (up to 10 main files)
        code_samples = fetch_code_files(owner, repo, file_structure, max_files=10)
        
        # Analyze the project based on files and code
        analysis = analyze_project(file_structure, code_samples, repo_info)
        
        # Generate a hardcore roast based on the detailed analysis
        roast = generate_roast_from_gemini(analysis)
        
        return jsonify({
            "repoName": repo_info.get("name", "Unknown"),
            "repoOwner": owner,
            "repoStars": repo_info.get("stargazers_count", 0),
            "repoForks": repo_info.get("forks_count", 0),
            "languages": analysis.get("languages"),
            "roast": roast
        })
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500


def fetch_repo_info(owner, repo):
    """Fetch basic repository information"""
    try:
        response = requests.get(f"https://api.github.com/repos/{owner}/{repo}", headers=headers)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        raise Exception(f"Error fetching repo info: {e}")


def fetch_file_content(owner, repo, path):
    """Fetch and decode file content"""
    try:
        response = requests.get(f"https://api.github.com/repos/{owner}/{repo}/contents/{path}", headers=headers)
        response.raise_for_status()
        content = response.json().get("content", "")
        if content:
            return base64.b64decode(content).decode("utf-8")
        return ""
    except requests.exceptions.RequestException as e:
        return f"Error fetching content: {e}"
    except UnicodeDecodeError:
        return "Binary file (not analyzed)"


def fetch_file_structure(owner, repo, path=""):
    """Recursively fetch file structure"""
    try:
        response = requests.get(f"https://api.github.com/repos/{owner}/{repo}/contents/{path}", headers=headers)
        response.raise_for_status()
        
        files = []
        for item in response.json():
            if item["type"] == "file":
                files.append(item["path"])
            elif item["type"] == "dir":
                files.extend(fetch_file_structure(owner, repo, item["path"]))  # Recursively fetch files inside directories
        
        return files
    except requests.exceptions.RequestException as e:
        raise Exception(f"Error fetching file structure: {e}")


def fetch_code_files(owner, repo, file_structure, max_files=10):
    """Fetch content of important code files for analysis"""
    code_files = []
    code_extensions = ['.py', '.js', '.jsx', '.ts', '.tsx', '.java', '.html', '.css', '.php', '.go', '.rb']
    
    # Filter to just code files
    code_file_paths = [f for f in file_structure if any(f.endswith(ext) for ext in code_extensions)]
    
    # Prioritize main files like app.py, index.js, main.py, etc.
    main_files = [f for f in code_file_paths if any(main_name in f.lower() for main_name in ['app', 'index', 'main', 'server'])]
    other_files = [f for f in code_file_paths if f not in main_files]
    
    # Fetch content from prioritized files
    prioritized_files = main_files + other_files
    for file_path in prioritized_files[:max_files]:  # Limit to max_files
        content = fetch_file_content(owner, repo, file_path)
        if content and len(content) > 0:
            code_files.append({
                "path": file_path,
                "content": content,
                "extension": os.path.splitext(file_path)[1]
            })
    
    return code_files


def identify_frameworks_from_code(code_files):
    """Identify frameworks and libraries based on code content"""
    frameworks = {
        "frontend": set(),
        "backend": set(),
        "database": set(),
        "other": set()
    }
    
    framework_patterns = {
        "React": (r'import\s+.*[^a-zA-Z]React[^a-zA-Z]', "frontend"),
        "Vue": (r'import\s+.*Vue|new\s+Vue', "frontend"),
        "Angular": (r'@angular|NgModule', "frontend"),
        "Express": (r'require\s*\(\s*[\'"]express[\'"]\s*\)|import\s+.*express', "backend"),
        "Flask": (r'from\s+flask\s+import|Flask\s*\(', "backend"),
        "Django": (r'from\s+django|DJANGO_|urls\.py', "backend"),
        "FastAPI": (r'from\s+fastapi\s+import|FastAPI\s*\(', "backend"),
        "Spring": (r'@SpringBootApplication|@Controller|@RestController', "backend"),
        "Laravel": (r'use\s+Illuminate|extends\s+Model', "backend"),
        "MongoDB": (r'mongoose|MongoDB|MongoClient', "database"),
        "MySQL": (r'mysql\.|createConnection|mysqli', "database"),
        "PostgreSQL": (r'psycopg2|pg\.|pgPool', "database"),
        "SQLite": (r'sqlite3|\.db', "database"),
        "TensorFlow": (r'import\s+tensorflow|import\s+tf', "other"),
        "PyTorch": (r'import\s+torch', "other"),
        "Redux": (r'createStore|useReducer|combineReducers|useSelector', "frontend"),
        "Tailwind": (r'tailwind|className="[^"]*flex[^"]*"', "frontend"),
        "Bootstrap": (r'bootstrap\.css|class="[^"]*btn[^"]*"', "frontend"),
        "jQuery": (r'\$\(|jQuery\(', "frontend"),
        "Socket.io": (r'socket\.io|io\.on\(', "backend"),
        "GraphQL": (r'graphql|ApolloClient|gql`', "backend"),
        "Webpack": (r'webpack\.config|module\.exports', "other"),
        "Docker": (r'Dockerfile|docker-compose', "other"),
    }
    
    for file in code_files:
        for framework, (pattern, category) in framework_patterns.items():
            if re.search(pattern, file["content"], re.IGNORECASE):
                frameworks[category].add(framework)
    
    return frameworks


def identify_code_issues(code_files):
    """Identify potential code issues for roasting"""
    issues = []
    
    # Common code smells and issues to look for
    patterns = {
        "Hardcoded credentials": r'password\s*=\s*[\'"][^\'"]+[\'"]|apiKey\s*=|secret\s*=',
        "Console logging": r'console\.log\(',
        "TODO comments": r'TODO|FIXME|XXX',
        "Empty catch blocks": r'catch\s*\([^)]*\)\s*{\s*}',
        "Magic numbers": r'\b\d{4,}\b',
        "Long functions": r'function\s+\w+\s*\([^)]*\)\s*{[^}]{500,}}',
        "Global variables": r'var\s+\w+\s*=|let\s+\w+\s*=|const\s+\w+\s*=',
        "Excessive comments": r'\/\*[\s\S]{50,}\*\/|\/\/.*\n\/\/.*\n\/\/.*\n\/\/.*\n\/\/.*\n',
        "Commented code": r'\/\/\s*function|\/\/\s*for\s*\(|\/\/\s*if\s*\(',
        "Variable naming": r'\b[a-z]{1,2}\b\s*=',
    }
    
    for file in code_files:
        file_issues = {}
        for issue, pattern in patterns.items():
            matches = re.findall(pattern, file["content"], re.MULTILINE)
            if matches:
                file_issues[issue] = len(matches)
        
        if file_issues:
            issues.append({
                "file": file["path"],
                "issues": file_issues
            })
    
    return issues


def check_inconsistent_styling(code_files):
    """Check for inconsistent styling across files"""
    issues = []
    
    # Check for inconsistent indentation
    indentation_styles = {}
    for file in code_files:
        if file["extension"] in [".py", ".js", ".jsx", ".ts", ".tsx"]:
            # Check for spaces vs tabs
            spaces = len(re.findall(r'^\s+', file["content"], re.MULTILINE))
            tabs = len(re.findall(r'^\t+', file["content"], re.MULTILINE))
            
            if spaces > tabs and tabs > 0:
                issues.append(f"Mixed spaces and tabs in {file['path']}")
            
            if spaces > 0:
                indentation_styles[file["path"]] = "spaces"
            elif tabs > 0:
                indentation_styles[file["path"]] = "tabs"
    
    # Check for inconsistent quotes
    quote_styles = {}
    for file in code_files:
        if file["extension"] in [".js", ".jsx", ".ts", ".tsx"]:
            single_quotes = len(re.findall(r'\'[^\']*\'', file["content"]))
            double_quotes = len(re.findall(r'\"[^\"]*\"', file["content"]))
            
            if single_quotes > double_quotes:
                quote_styles[file["path"]] = "single"
            elif double_quotes > single_quotes:
                quote_styles[file["path"]] = "double"
    
    # Check if both styles are used across the project
    if len(set(indentation_styles.values())) > 1:
        issues.append("Inconsistent indentation (both spaces and tabs used)")
    
    if len(set(quote_styles.values())) > 1:
        issues.append("Inconsistent quotation mark style")
    
    return issues


def analyze_project(file_structure, code_samples, repo_info):
    """Create a detailed analysis of the project for roasting"""
    # Basic repo stats
    analysis = {
        "name": repo_info.get("name", "Unknown"),
        "description": repo_info.get("description", "No description"),
        "stars": repo_info.get("stargazers_count", 0),
        "forks": repo_info.get("forks_count", 0),
        "issues": repo_info.get("open_issues_count", 0),
        "file_count": len(file_structure),
        "languages": [],
        "frameworks": {},
        "code_issues": [],
        "styling_issues": [],
        "complexity": "simple",
        "structure_issues": [],
        "copied_code_likelihood": "low"
    }
    
    # Calculate language breakdown
    language_extensions = {
        ".py": "Python",
        ".js": "JavaScript",
        ".jsx": "React/JavaScript",
        ".ts": "TypeScript",
        ".tsx": "React/TypeScript",
        ".html": "HTML",
        ".css": "CSS",
        ".java": "Java",
        ".php": "PHP",
        ".go": "Go",
        ".rb": "Ruby",
        ".c": "C",
        ".cpp": "C++",
        ".cs": "C#",
    }
    
    language_count = {}
    for file in file_structure:
        ext = os.path.splitext(file)[1].lower()
        if ext in language_extensions:
            lang = language_extensions[ext]
            language_count[lang] = language_count.get(lang, 0) + 1
    
    # Sort languages by frequency
    analysis["languages"] = sorted(language_count.items(), key=lambda x: x[1], reverse=True)
    
    # Identify frameworks from code content
    if code_samples:
        analysis["frameworks"] = identify_frameworks_from_code(code_samples)
        
        # Add code issues for roasting
        analysis["code_issues"] = identify_code_issues(code_samples)
        
        # Look for styling inconsistencies
        analysis["styling_issues"] = check_inconsistent_styling(code_samples)
        
        # Check project structure
        if ".git" not in [os.path.basename(f) for f in file_structure]:
            analysis["structure_issues"].append("No Git repository")
        
        if not any("README" in f for f in file_structure):
            analysis["structure_issues"].append("No README file")
        
        if not any("requirements.txt" in f for f in file_structure) and any(f.endswith(".py") for f in file_structure):
            analysis["structure_issues"].append("Python project without requirements.txt")
        
        if not any("package.json" in f for f in file_structure) and any(f.endswith(".js") for f in file_structure):
            analysis["structure_issues"].append("JavaScript project without package.json")
    
    # Determine project complexity
    if analysis["file_count"] < 10:
        analysis["complexity"] = "bahut simple aur bekaar" # Very simple and useless
    elif analysis["file_count"] < 30:
        analysis["complexity"] = "thoda sa complex lekin fir bhi bakwaas" # A bit complex but still nonsense
    else:
        analysis["complexity"] = "complex lekin bekar implementation ke saath" # Complex but with terrible implementation
    
    # Estimate likelihood of code copying based on patterns
    if any("COPYRIGHT" in f for f in file_structure) or any("LICENSE" in f for f in file_structure):
        analysis["copied_code_likelihood"] = "high"
    
    return analysis


def generate_roast_from_gemini(analysis):
    """Generate an extreme roast in Hinglish using Gemini API"""
    try:
        # Extract key information for the prompt
        languages = [f"{name} ({count} files)" for name, count in analysis.get("languages", [])]
        frontend_fw = list(analysis.get("frameworks", {}).get("frontend", []))
        backend_fw = list(analysis.get("frameworks", {}).get("backend", []))
        database_fw = list(analysis.get("frameworks", {}).get("database", []))
        
        # Get code samples for specific roasting
        code_issues = []
        for issue in analysis.get("code_issues", []):
            file_name = issue["file"].split("/")[-1]
            issue_list = []
            for issue_type, count in issue["issues"].items():
                issue_list.append(f"{issue_type} ({count})")
            code_issues.append(f"{file_name}: {', '.join(issue_list)}")
        
        # Create a detailed prompt for Gemini - now in Hinglish
        prompt = f"""
        Main ek GitHub project ke liye Hinglish me ek bahut hi kathor aur apmaanjanak roast generate karna chahta hoon. Yeh project bahut bura code hai aur mujhe ise bahut aggressive aur mazakiya tarike se roast karna hai.

        Project ka naam: {analysis.get('name')}
        Description: {analysis.get('description')}
        Stars: {analysis.get('stars')}
        Forks: {analysis.get('forks')}
        Files ki sankhya: {analysis.get('file_count')}
        Complexity: {analysis.get('complexity')}
        
        Languages: {', '.join(languages) if languages else 'Kuch nahi mila'}
        Frontend frameworks: {', '.join(frontend_fw) if frontend_fw else 'Kuch nahi mila'}
        Backend frameworks: {', '.join(backend_fw) if backend_fw else 'Kuch nahi mila'}
        Database technologies: {', '.join(database_fw) if database_fw else 'Kuch nahi mila'}
        
        Code mein problems: {', '.join(code_issues) if code_issues else 'Kuch nahi mila'}
        
        Structure mein problems: {', '.join(analysis.get('structure_issues', []))}
        Styling mein problems: {', '.join(analysis.get('styling_issues', []))}
        
        Roast ke instructions:
        1. Sirf Hinglish language ka prayog karein (Hindi words written in English script with gaaliyaan and bahut aggressive language)
        2. Bahut lamba hona chahiye (200 words)
        3. Atyant kathor aur aggressive hona chahiye (sabse buri Hinglish gaaliyaan)
        4. Unke coding skills aur technical choices ka mazaak udaayein
        5. Unke code ki kharab quality, framework mein bure choices ya structure problems ke baare mein specific mentions include karein
        6. Aise likhein jaise aap unke code ki buraai se bahut naraaz hain
        7. Unke code mein kam se kam 3 problems ka specific mention karein
        8. Pure roast mein Hinglish gaaliyaan ka khub upyog karein
        9. Unke code ki tulna kachre ya maal se kai baar karein
        10. Mazedaar scenarios banayein ki agar is code ka upyog production mein kiya jaata to kitna bura hota
        11. Yeh batane ke liye Hinglish mein rupak aur upmaayein ka upyog karein ki code kitna bura hai
        
        Yeh adults ke liye hai jo kathor roast chahte hain - bilkul bhi sankoch na karein. Sabse kharab Hinglish gaaliyaan ka upyog karein.
        """
        
        # Set up Gemini model parameters - use high temperature for creativity
        model = genai.GenerativeModel(
            model_name="gemini-pro",
            generation_config={
                "temperature": 1.0,  # Increased for more creative and extreme output
                "top_p": 0.98,
                "top_k": 50,
                "max_output_tokens": 1200,  # Increased for longer roast
                "candidate_count": 1,
            },
            safety_settings=[
                {
                    "category": "HARM_CATEGORY_HARASSMENT",
                    "threshold": "BLOCK_ONLY_HIGH",
                },
                {
                    "category": "HARM_CATEGORY_HATE_SPEECH",
                    "threshold": "BLOCK_ONLY_HIGH",
                },
                {
                    "category": "HARM_CATEGORY_SEXUALLY_EXPLICIT",
                    "threshold": "BLOCK_ONLY_HIGH",
                },
                {
                    "category": "HARM_CATEGORY_DANGEROUS_CONTENT",
                    "threshold": "BLOCK_ONLY_HIGH",
                },
            ]
        )
        
        # Generate response with retries if needed
        max_attempts = 3
        for attempt in range(max_attempts):
            try:
                response = model.generate_content(prompt)
                
                # Check if we got a valid response
                if response and hasattr(response, 'text') and len(response.text.strip()) > 100:
                    return response.text
                
                # If the response is too short, add a note and try again with modified prompt
                prompt += f"\n\nPlease try again and don't hold back. This is for comedy purposes and the recipient wants to be roasted harshly."
                time.sleep(1)  # Short pause between attempts
            except Exception as inner_e:
                print(f"Attempt {attempt+1} failed: {inner_e}")
                time.sleep(2)  # Slightly longer pause after an error
        
        # If all attempts fail, use fallback
        return generate_fallback_roast(analysis)
            
    except Exception as e:
        # Log the error and use fallback
        print(f"Error with Gemini API: {e}")
        return generate_fallback_roast(analysis)


def generate_fallback_roast(analysis):
    """Generate a fallback hardcore roast in Hinglish if API fails"""
    insults = [
        "Tumhara code dekhkar meri aankhen jal gayi hain",
        "Yeh code nahi, yeh to mere toilet se bhi ganda hai",
        "Tumhare code se achcha to mera 5 saal ka baccha likh dega",
        "Ise code kehte ho? Yeh to sirf bakwaas hai",
        "Tumhara project dekhkar mujhe ulti aa rahi hai",
        "Tumhara GitHub dekhkar main hans-hanskar lot-pot ho gaya",
        "Tumhare code ki architecture chaprasi ne design ki hai kya?",
        "Tum programmer nahi, keyboard par haath maarne wale bandar ho",
        "Tumhare functions ka naam dekhkar mere kaan se khoon nikal gaya",
        "Tumhara code chalta kaise hai? Chamatkar hai kya?",
        "Is project ko banane mein kitni copy-paste ki?",
        "Tumhara code dekhkar Stack Overflow bhi sharma jayega",
        "Tumhare variable name dekhkar mera sir chakra gaya"
    ]
    
    # Main language from analysis
    main_language = analysis.get("languages", [["Unknown", 0]])[0][0] if analysis.get("languages") else "Unknown"
    
    # Build a hardcore roast from templates and analysis data
    roast_parts = []
    
    # Introduction
    roast_parts.append(f"Are {analysis.get('name', 'bewakoof')}, yeh kya haga hai tune? Yeh code hai ya teri zindagi ki tarah barbaadi ka ek aur namoona?")
    
    # Language specific insults
    if "Python" in main_language:
        roast_parts.append(f"Tere {main_language} ke code ko dekhkar Python ke nirmaata Guido van Rossum khud faansi laga lenge. Itna ganda code to maine kabhi nahi dekha jo tumne {analysis.get('file_count', 0)} files mein failaya hai.")
    elif "JavaScript" in main_language or "React" in main_language:
        roast_parts.append(f"Tere {main_language} mein to koi serial killer se zyada gandagi hai. {analysis.get('file_count', 0)} files aur sabhi kachre se bhari hui hain. Tere code ki wajah se Chrome browser aatmahatya kar lega.")
    elif "Java" in main_language:
        roast_parts.append(f"Tere {main_language} code ko dekhkar meri gaand fat gayi. Itna verbose aur bakwaas code to narak mein bhi nahi milega. {analysis.get('file_count', 0)} files ka bojh aur sab kuch teri tarah bekaar.")
    else:
        roast_parts.append(f"Tere {main_language} code se to kutte ka moot bhi behtar hai. {analysis.get('file_count', 0)} files mein sirf teri bakwaas bhari hai, koi kaam ka code to hai hi nahi.")
    
    # Issues in code structure
    if analysis.get("structure_issues"):
        issues = ', '.join(analysis.get("structure_issues"))
        roast_parts.append(f"Tere project ki structure behad gandi hai - {issues}. Tu code likhne layak nahi hai, tu sirf tatti kar sakta hai jise tune code ke naam par GitHub par daal diya hai.")
    
    # Styling issues
    if analysis.get("styling_issues"):
        issues = ', '.join(analysis.get("styling_issues"))
        roast_parts.append(f"Teri coding style dekhkar mujhe ulti aa gayi - {issues}. Kya tu coding standards ke baare mein kuch jaanta bhi hai ya bas apni gaand se code nikalta hai?")
    
    # Framework choices
    frontend = list(analysis.get("frameworks", {}).get("frontend", []))
    backend = list(analysis.get("frameworks", {}).get("backend", []))
    
    if frontend:
        fw = ', '.join(frontend)
        roast_parts.append(f"Tune {fw} ka istemal kiya hai frontend ke liye? Waah! Teri bakwaas selection dekhkar to frontend developers ki aatma ro rahi hogi. Chutiya kahin ka!")
    
    if backend:
        fw = ', '.join(backend)
        roast_parts.append(f"Aur backend ke liye {fw}? Madarchod, itni bekaar technique chunne ke liye tujhe sochna pada tha ya tune random tarike se chun liya? Tera server to Hindustan ke sarkari website se bhi dheema chalega!")
    
    # Complexity
    roast_parts.append(f"Aur tere code ki complexity {analysis.get('complexity')}? Behenchod, tune itna jatil aur bekaar code kaise likha? Tu pagal hai kya? Ya fir tu sirf apne aap ko smart dikhana chahta hai, lekin tera code teri aukat dikha raha hai - ekdam ganwar ki tarah!")
    
    # Code issues
    if analysis.get("code_issues"):
        code_issues = analysis.get("code_issues")[:3]  # Take up to 3 issues
        issue_descriptions = []
        
        for issue in code_issues:
            file = issue["file"]
            problems = list(issue["issues"].keys())[:2]  # Take up to 2 problems per file
            issue_descriptions.append(f"{file} mein {', '.join(problems)}")
        
        issues_text = ', '.join(issue_descriptions)
        roast_parts.append(f"Tere code mein itni problems hain ki mujhe hansi aa rahi hai - {issues_text}. Ye tere code ki galtiyan nahi, tere janam ki galtiyan hain. Tu programmer banne ke layak nahi hai, tu sirf sadak par bheekh maangne ke layak hai.")
    
    # Stars and forks
    stars = analysis.get("stars", 0)
    forks = analysis.get("forks", 0)
    
    if stars < 5:
        roast_parts.append(f"Tere project ko matra {stars} stars mile hain? Itne to main apni gaand se nikaal dunga! Tera code itna bakwaas hai ki log ise dekhkar bhaag jaate hain.")
    
    if forks < 2:
        roast_parts.append(f"Aur sirf {forks} forks? Madarchod, tere code ko koi chhoona bhi nahi chahta! Kyunki tera code dekhne ke baad logon ka vishwas hi uth gaya hai manav jaati se!")
    
    # Production scenarios
    roast_parts.append("Agar tere is kamine code ko production mein daala gaya, to pura server aag pakad lega. Users tere ghar par patthar maarne aayenge aur tere parivar waale tujhse apna rishta tod lenge. Tu beghar ho jayega aur sadak par sote hue kutte tere muh par moot denge.")
    
    # More analogies and metaphors
    roast_parts.append("Tera code us gobar ke dher ki tarah hai jisme suar lot rahe hon. Ise chhoone se pehle 10 baar haath dhone padenge aur fir bhi gandagi nahi jayegi. Tere functions aise hain jaise kisi anpadh ganwar ne angrezi ke shabd ratte maare hon.")
    
    # Random insults from the list
    random.shuffle(insults)
    roast_parts.extend(insults[:4])  # Add 4 random insults
    
    # Conclusion
    roast_parts.append("Ant mein, tere code ki gandagi itni zyada hai ki Ganga nadi mein dubki lagakar bhi shuddh nahi hogi. Agar tu sach mein programmer banna chahta hai, to apna laptop bech de aur ja ke gaay chara. Coding tere bas ki baat nahi hai, bhosadike!")
    
    # Combine all parts
    return "\n\n".join(roast_parts)


if __name__ == "__main__":
    # Get port from environment variable or use default
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)