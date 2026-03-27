# 🚀 Gen-AI Workflow System (AI + SLA Automation)

🔗 **Live App:** [https://gen-ai-workflow.vercel.app](https://gen-ai-workflow.vercel.app)

---

## 🧠 Overview

Gen-AI Workflow is an AI-powered complaint management system that automates the entire lifecycle of a case — from submission to escalation.

The system uses AI to analyze complaints, assign priorities, route them to appropriate personnel, and monitor SLA deadlines. If a case exceeds its SLA, an automated escalation email is generated using AI and sent to the assigned user.

---

## ⚙️ Tech Stack

* Backend: Flask
* Frontend: HTML / Bootstrap
* Database: Supabase (PostgreSQL)
* AI: Google Gemini
* Email Service: EmailJS
* Serverless Jobs: Supabase Edge Functions, Cron Job
* Deployment: Vercel

---

## 🔥 Features

* Gen-AI-based complaint analysis and summarization
* Intelligent case routing and assignment
* SLA tracking using timestamp-based deadlines
* Automated escalation for overdue cases
* AI-generated professional email notifications
* Audit logging for all case activities
* Role-based access (Owner / Worker)

---

## 🔐 Demo Login

You can explore the system using the following demo credentials:

Email: [demo@gen-ai-workflow.com](mailto:demo@gen-ai-workflow.com)
Password: Demo@1234

---

## ⏱️ SLA & Escalation System

* SLA is stored as an absolute timestamp:
  created_at + SLA hours
* A cron job runs every 60 minutes
* It triggers a Supabase Edge Function
* Overdue cases are detected automatically
* AI generates an escalation email
* Email is sent to the assigned user
* Case is marked as notified

---

## 🏗️ Architecture

User submits complaint  
        ↓  
AI analyzes (Gemini)  
        ↓  
Priority + SLA assigned  
        ↓  
Case stored in Supabase  
        ↓  
Cron Job (every 60 mins)  
        ↓  
Triggers Edge Function  
        ↓  
Check overdue cases  
        ↓  
Gemini generates email  
        ↓  
EmailJS sends notification  
        ↓  
Case marked as escalated  

---

## ⚙️ Setup Instructions

1. Clone the repository

git clone [https://github.com/saimohith-27/Gen-AI-Workflow](https://github.com/saimohith-27/Gen-AI-Workflow)
cd gen-ai-workflow

2. Create virtual environment and install dependencies

python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt

3. Create `.env` file
  
FLASK_SECRET=your_secret  

SUPABASE_URL=your_project_url  
SUPABASE_SERVICE_ROLE_KEY=your_service_role_key  
  
GEMINI_API_KEY=your_gemini_key  
  
EMAILJS_SERVICE_ID=your_service    
EMAILJS_TEMPLATE_ID=your_template_id  
EMAILJS_PUBLIC_KEY=your_public_key  
EMAILJS_PRIVATE_KEY=your_private_key  

4. Run the app

python app.py

Open: [http://localhost:5000](http://localhost:5000)

---

## 🚀 Key Concepts Demonstrated

* Gen-AI integration in real-world workflows
* Backend system design
* Serverless architecture
* Scheduled background jobs (cron)
* Database modeling with SLA tracking
* Async processing and automation

---

## 👨‍💻 Author

[GOPISETTY SAI MOHITH](https://github.com/saimohith-27)

---

## ⭐ Note

This project demonstrates how Gen-AI can be integrated into real-world systems to automate workflows, improve efficiency, and handle escalation intelligently.

---
