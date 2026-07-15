# 🛒 Sainsbury's Retail AI Assistant — Beginner's Guide

This document explains the entire project in plain English. By the time you finish reading, you should be able to confidently talk about it to teammates, interviewers, or clients.

---

## 1. What Is This Project?

This is an **AI-powered customer support assistant** built for a Sainsbury's (UK supermarket) website. Think of it as a very smart chatbot that can:

- Answer questions about your orders ("Where is my delivery?")
- Help with refunds ("I received a damaged item")
- Find product information ("Is this gluten-free?")
- Check store hours and locations
- Talk to you by voice — like a real phone call

The chatbot works via **text chat** on the website AND via a **live voice call** (just like calling a real agent, but it's AI).

---

## 2. Why Was It Built?

Most retail chatbots give generic answers like *"Please contact our support team."* This project was built to do the opposite — it gives **real, personalised answers** by:

- Looking up **your specific orders** (e.g., "Your order ORD-99102 was delivered by Maria on June 16")
- Checking **real-time stock** at your nearest store
- Processing **refunds on the spot**
- Updating your **delivery address**

It replaces the need for a live human agent for the most common customer queries.

---

## 3. Who Uses It?

| Who | What they do |
|-----|-------------|
| **Customers** | Chat or call to get support about orders, deliveries, refunds, and products |
| **Developers** | Maintain and extend the chatbot |
| **Managers/Clients** | View the product demo, evaluate capabilities |

---

## 4. Main Features

| Feature | Description |
|---------|-------------|
| 💬 **Text Chat** | Type questions and get smart AI-powered answers |
| 📦 **Order Tracking** | Real status of your orders from the database |
| 💸 **Refund Processing** | Issues refunds instantly |
| 🏪 **Store Finder** | Finds nearby stores, checks hours and stock |
| 🎤 **Browser Voice** | Click a call button, speak to an AI in real time |
| 📞 **PSTN Phone Call** | Real telephone call routed through Azure |
| 🤖 **5 Specialist Agents** | Each topic (orders, refunds, store, delivery) has its own dedicated AI agent |
| 🔒 **Security Guardrails** | Blocks the AI from revealing internal data, API keys, or other customers' details |
| ⚡ **Streaming Responses** | Words appear on screen as the AI types (like ChatGPT) |

---

## 5. Technologies Used at a Glance

| What | Technology |
|------|-----------|
| Frontend (Website UI) | Plain HTML + CSS + JavaScript |
| Backend (Server) | Python + FastAPI |
| AI Orchestration | LangGraph |
| AI Models | Azure AI Foundry (GPT-5-mini) |
| Voice (Real-time) | Azure Voice Live SDK |
| Phone Calls | Azure Communication Services |
| Database | SQLite (local) / PostgreSQL (production) |
| Product Search | Azure AI Search |
| Deployment | Vercel (serverless) |
