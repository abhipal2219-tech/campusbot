/* ===================================================
   Campus Connect — script.js
   Merged: vector-store + search-engine + chatbot-ui
   
   AI calls go to the Python backend on Render.
   No API keys stored in this file.
   =================================================== */

// ── Backend URL ────────────────────────────────────────
// Replace this with your Render service URL after deploying.
// e.g. "https://campusbot-xyz.onrender.com"
const BACKEND_URL = 'https://campusbot-vqvx.onrender.com';

// =======================================================
// 1. VectorStore — client-side TF-IDF search
// =======================================================
class VectorStore {
    constructor() {
        this.docs  = [];
        this.idf   = {};
        this._dirty = true;
    }

    tokenize(text) {
        return text.toLowerCase()
            .replace(/[.\-\/]/g, ' ')
            .replace(/[^a-z0-9\s]/g, '')
            .split(/\s+/)
            .filter(Boolean);
    }

    addDoc(text, meta) {
        const tokens = this.tokenize(text);
        const tf = {};
        tokens.forEach(t => { tf[t] = (tf[t] || 0) + 1; });
        Object.keys(tf).forEach(t => { tf[t] /= tokens.length; });
        this.docs.push({ text, meta, tf });
        this._dirty = true;
    }

    _buildIDF() {
        const N = this.docs.length;
        if (!N) return;
        const df = {};
        this.docs.forEach(d => {
            Object.keys(d.tf).forEach(t => { df[t] = (df[t] || 0) + 1; });
        });
        this.idf = {};
        Object.keys(df).forEach(t => {
            this.idf[t] = Math.log((N + 1) / (df[t] + 1)) + 1;
        });
        this._dirty = false;
    }

    _vec(tf) {
        const v = {};
        Object.keys(tf).forEach(t => { v[t] = tf[t] * (this.idf[t] || 0); });
        return v;
    }

    _cos(a, b) {
        const keys = Object.keys(a).filter(k => b[k]);
        if (!keys.length) return 0;
        const dot  = keys.reduce((s, k) => s + a[k] * b[k], 0);
        const normA = Math.sqrt(Object.values(a).reduce((s, v) => s + v * v, 0));
        const normB = Math.sqrt(Object.values(b).reduce((s, v) => s + v * v, 0));
        return (normA && normB) ? dot / (normA * normB) : 0;
    }

    search(query, topK = 5) {
        if (this._dirty) this._buildIDF();
        const qTF = {};
        const qTokens = this.tokenize(query);
        qTokens.forEach(t => { qTF[t] = (qTF[t] || 0) + 1; });
        Object.keys(qTF).forEach(t => { qTF[t] /= qTokens.length; });
        const qVec = this._vec(qTF);

        return this.docs
            .map(d => ({ text: d.text, meta: d.meta, score: this._cos(qVec, this._vec(d.tf)) }))
            .filter(r => r.score > 0)
            .sort((a, b) => b.score - a.score)
            .slice(0, topK);
    }
}

// =======================================================
// 2. SearchEngine — data loader + response logic
// =======================================================
const SearchEngine = {
    faculty:  [],
    rooms:    [],
    sections: [],
    ragDB:    new VectorStore(),

    // ── Conversation memory ──
    chatHistory: [],
    _lastEntity: null,
    _lastSection: null,
    MAX_HISTORY: 6,

    _addToHistory(role, content) {
        this.chatHistory.push({ role, content: content.substring(0, 300) });
        if (this.chatHistory.length > this.MAX_HISTORY) this.chatHistory.shift();
    },

    _resolvePronouns(input) {
        const pronouns = /\b(she|he|they|her|his|him|this teacher|that teacher|this person|that person|this faculty|that faculty|this sir|this mam|this madam|that sir|that mam)\b/i;
        if (pronouns.test(input) && this._lastEntity) {
            return input.replace(pronouns, this._lastEntity);
        }
        return input;
    },

    _trackEntity(name, section) {
        if (name) this._lastEntity = name;
        if (section) {
            this._lastSection = section;
            this._lastEntity  = section.classTeacher.name.split('(')[0].trim();
        }
    },

    // ── Load data from backend/data/ (served as static files in dev, 
    //    but fetched from the same origin on GitHub Pages) ──
    async init() {
        try {
            const [f, r, s] = await Promise.all([
                fetch('data/faculty.json').then(res => { if (!res.ok) throw new Error(); return res.json(); }),
                fetch('data/rooms.json').then(res => { if (!res.ok) throw new Error(); return res.json(); }),
                fetch('data/sections.json').then(res => { if (!res.ok) throw new Error(); return res.json(); }),
            ]);
            this.faculty  = f;
            this.rooms    = r;
            this.sections = s;
            this._buildRAG();
            return true;
        } catch (e) {
            console.error('[SearchEngine] Failed to load campus data:', e);
            return false;
        }
    },

    _buildRAG() {
        this.rooms.forEach(r => {
            this.ragDB.addDoc(
                `${r.use} is in ${r.bld}, ${r.floor}, Room ${r.room}`,
                { type: 'room', ...r }
            );
        });
        this.faculty.forEach(f => {
            this.ragDB.addDoc(
                `${f.name} (${f.code}) is in ${f.dept} dept. Cabin: ${f.room}`,
                { type: 'faculty', ...f }
            );
        });
        this.sections.forEach(s => {
            const mentors = (s.mentors || []).join(', ');
            this.ragDB.addDoc(
                `Section ${s.section} is in ${s.block}, ${s.floor}, Room ${s.room}. ` +
                `Teacher: ${s.classTeacher.name}, Phone: ${s.classTeacher.phone}. Mentors: ${mentors}`,
                { type: 'section', ...s }
            );
        });
    },

    norm(s) {
        return s.toLowerCase().replace(/[.\-\/]/g, ' ').replace(/\s+/g, ' ').trim();
    },

    // Direct keyword match for rooms and faculty
    _directSearch(input) {
        const q     = this.norm(input);
        const words = q.split(' ').filter(w => w.length > 2);
        if (!words.length) return [];

        const score = (text) => {
            const t = text.toLowerCase().replace(/[.\-\/]/g, ' ');
            return words.filter(w => t.includes(w)).length / words.length;
        };

        const roomHits = this.rooms
            .map(r => ({ score: score(r.use + ' ' + r.bld + ' ' + r.room), data: r, type: 'room' }))
            .filter(x => x.score >= 0.4)
            .sort((a, b) => b.score - a.score)
            .slice(0, 3);

        const facHits = this.faculty
            .map(f => ({ score: score(f.name + ' ' + f.dept + ' ' + (f.code || '')), data: f, type: 'faculty' }))
            .filter(x => x.score >= 0.5)
            .sort((a, b) => b.score - a.score)
            .slice(0, 3);

        if (roomHits.length) return roomHits;
        return facHits;
    },

    // ── Call the Render backend for AI-powered answers ──
    async _callBackend(message) {
        if (!BACKEND_URL || BACKEND_URL === 'YOUR_RENDER_URL') {
            // Backend not configured yet — return null to use local fallback
            return null;
        }
        try {
            const res = await fetch(`${BACKEND_URL}/chat`, {
                method:  'POST',
                headers: { 'Content-Type': 'application/json' },
                body:    JSON.stringify({
                    message,
                    history: this.chatHistory.slice(-4)
                })
            });
            if (!res.ok) return null;
            const data = await res.json();
            return data.reply || null;
        } catch (e) {
            console.warn('[SearchEngine] Backend unreachable:', e.message);
            return null;
        }
    },

    // ── Main response logic ──
    async findResponse(rawInput) {
        const input = this._resolvePronouns(rawInput);
        this._addToHistory('user', rawInput);

        const q     = this.norm(input);
        const words = q.split(' ').filter(w => w.length > 2);

        // 1. Greetings
        if (/^(hi|hello|hey|good\s*(morning|afternoon|evening)|start|help)$/.test(q)) {
            return "👋 Hi! I'm <strong>Campus Connect</strong>. I can help you find <strong>sections</strong>, <strong>faculty cabins</strong>, and <strong>room locations</strong> at UEM Kolkata!";
        }

        // 2. Section match
        const secMatch = input.match(/section\s*([A-P])\b/i)
                      || input.match(/\bsec\s+([A-P])\b/i);
        if (secMatch) {
            const letter = secMatch[1].toUpperCase();
            const s = this.sections.find(x => x.section === letter);
            if (s) {
                if (/teacher|class\s*teacher/i.test(input)) {
                    this._trackEntity(null, s);
                    const reply = `👨‍🏫 Class Teacher of <strong>Section ${s.section}</strong>:<br><br>` +
                        `<strong>${s.classTeacher.name}</strong><br>` +
                        `📞 Phone: <strong>${s.classTeacher.phone}</strong><br>` +
                        `📧 Email: <strong>${s.classTeacher.email}</strong><br>` +
                        `📍 Room: <strong>${s.room}</strong> (${s.block}, ${s.floor})`;
                    this._addToHistory('assistant', reply);
                    return reply;
                }
                if (/mentor/i.test(input)) {
                    const mentors = s.mentors || [];
                    if (mentors.length) {
                        return `🧑‍🏫 Mentors of <strong>Section ${s.section}</strong>:<br><br>` +
                            mentors.map(m => `▸ <strong>${m}</strong>`).join('<br>') +
                            `<br><br>📍 Room: <strong>${s.room}</strong> (${s.block}, ${s.floor})`;
                    }
                    return `😔 No mentors recorded for Section ${s.section}.`;
                }
                this._trackEntity(null, s);
                const reply = this._formatSection(s);
                this._addToHistory('assistant', reply);
                return reply;
            }
        }

        // 3. Faculty name match
        const skipWords = new Set([
            'prof','dr','sir','mam','madam','teacher','class','mentor',
            'department','where','find','who','show','all','the','is',
            'section','room','cabin','what','tell','about','list'
        ]);
        const nameHits = this.faculty.filter(f => {
            const fn = this.norm(f.name);
            return words.some(w => fn.includes(w) && !skipWords.has(w));
        });
        if (nameHits.length > 0 && nameHits.length < 4) {
            this._trackEntity(nameHits[0].name, null);
            const reply = nameHits.map(f => this._formatFaculty(f)).join('<hr>');
            this._addToHistory('assistant', reply);
            return reply;
        }

        // 4. Room number match
        const roomMatch = input.match(/\b(B[123][\s\-]?(?:LG[\s\-]?)?\d+\.?\d*(?:\s*\([AB]\))?)\b/i);
        if (roomMatch) {
            const key = this.norm(roomMatch[1]);
            const hits = this.rooms.filter(x => this.norm(x.room).includes(key));
            if (hits.length) return hits.map(x => this._formatRoom(x)).join('<hr>');
        }

        // 5. Direct keyword search
        const directHits = this._directSearch(input);
        if (directHits.length) {
            const parts = directHits.map(d => {
                if (d.type === 'room')    return this._formatRoom(d.data);
                if (d.type === 'faculty') return this._formatFaculty(d.data);
                return '';
            }).filter(Boolean);
            if (parts.length) return parts.join('<hr>');
        }

        // 6. Backend AI call (Render/Groq)
        const aiReply = await this._callBackend(rawInput);
        if (aiReply) {
            const reply = this._formatAI(aiReply);
            this._addToHistory('assistant', reply);
            return reply;
        }

        // 7. Fallback
        const campusKeywords = [
            'section','room','block','floor','teacher','faculty','mentor',
            'cabin','where','find','who','list','dept','library','cafeteria',
            'gym','office','lab'
        ];
        if (campusKeywords.some(kw => q.includes(kw))) {
            return "🤔 I couldn't find a precise match. Could you be more specific? (e.g., <em>'Where is Section G?'</em> or <em>'Electrical lab room'</em>)";
        }
        return "😔 I only know about UEM Kolkata campus. Please check the notice board for other information.";
    },

    // ── Formatters ──
    _formatAI(text) {
        return text
            .replace(/\*\*\*(.+?)\*\*\*/g, '<strong><em>$1</em></strong>')
            .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
            .replace(/^[•\-\*]\s+(.+)$/gm, '<div style="padding:2px 0 2px 4px;">▸ $1</div>')
            .replace(/^(\d+)\.\s+(.+)$/gm, '<div style="padding:2px 0;"><span style="color:#a78bfa;font-weight:600;">$1.</span> $2</div>')
            .replace(/\n{2,}/g, '<br><br>')
            .replace(/\n/g, '<br>');
    },

    _formatSection(s) {
        const mentors = (s.mentors || []).join(', ');
        return `📍 <strong>Section ${s.section}</strong><br>🏢 ${s.block} — ${s.floor}<br>🚪 Room: <strong>${s.room}</strong><hr>` +
               `👨‍🏫 Teacher: <strong>${s.classTeacher.name}</strong><br>📞 ${s.classTeacher.phone}<br>📧 ${s.classTeacher.email}` +
               (mentors ? `<hr>🧑‍🏫 Mentors:<br>${(s.mentors || []).map(m => `▸ <strong>${m}</strong>`).join('<br>')}` : '');
    },

    _formatRoom(r) {
        return `🏢 <strong>${r.use}</strong><br>📍 <strong>${r.bld}</strong>, ${r.floor}<br>🚪 Room: <strong>${r.room}</strong>`;
    },

    _formatFaculty(f) {
        return `<strong>${f.name}</strong> <span class="dept-tag">${f.dept}</span>` +
               (f.code ? `<span class="dept-tag">🏷 ${f.code}</span>` : '') +
               `<br>🚪 Cabin: <strong>${f.room || 'Not recorded — check notice board'}</strong>`;
    }
};

window.SearchEngine = SearchEngine;

// =======================================================
// 3. UI Controller — Obsidian Glass / Noir Design
// =======================================================
const UI = {
    msgEl:   document.getElementById('chatMessages'),
    inputEl: document.getElementById('userInput'),
    sendBtn: document.getElementById('sendBtn'),
    isBusy:  false,

    init() {
        this.sendBtn.addEventListener('click',   () => this.handleSend());
        this.inputEl.addEventListener('keydown', e => e.key === 'Enter' && this.handleSend());
        this._welcome();
    },

    quickSend(text) {
        this.inputEl.value = text;
        this.handleSend();
    },

    _welcome() {
        this.addMessage('bot',
            `<strong>Campus Connect</strong> — system online.<br><br>` +
            `I can find sections, faculty cabins, room locations, and mentors for UEM Kolkata.`
        );
        this.addChips(['Where is Section G?', 'Where is the library?', 'Section E mentors', 'Show Physics faculty']);
    },

    async handleSend() {
        const text = this.inputEl.value.trim();
        if (!text || this.isBusy) return;

        this.addMessage('user', text);
        this.inputEl.value = '';
        this.showTyping();

        try {
            const reply = await window.SearchEngine.findResponse(text);
            this.hideTyping();
            this.addMessage('bot', reply
                ? reply.replace(/\n/g, '<br>')
                : "No records found for that query."
            );
        } catch (e) {
            this.hideTyping();
            this.addMessage('bot', 'System error — please try again.');
            console.error('[UI]', e);
        }
    },

    _time() {
        return new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    },

    addMessage(role, html) {
        const wrap = document.createElement('div');
        wrap.className = `msg ${role}`;

        const bub = document.createElement('div');
        bub.className = 'bubble';
        bub.innerHTML = html;

        const time = document.createElement('div');
        time.className   = 'msg-time';
        time.textContent = this._time();

        wrap.appendChild(bub);
        wrap.appendChild(time);
        this.msgEl.appendChild(wrap);
        this._scrollToBottom();
    },

    addChips(chips) {
        const div = document.createElement('div');
        div.className = 'quick-replies';
        chips.forEach(c => {
            const btn = document.createElement('button');
            btn.className   = 'quick-btn';
            btn.textContent = c;
            btn.onclick = () => { div.remove(); this.quickSend(c); };
            div.appendChild(btn);
        });
        this.msgEl.appendChild(div);
        this._scrollToBottom();
    },

    showTyping() {
        this.isBusy = true;
        const w = document.createElement('div');
        w.id        = 'typing-indicator';
        w.className = 'msg bot';

        const bub = document.createElement('div');
        bub.className = 'bubble';
        bub.innerHTML = '<div class="cursor-block"></div>';

        w.appendChild(bub);
        this.msgEl.appendChild(w);
        this._scrollToBottom();
    },

    _scrollToBottom() {
        requestAnimationFrame(() => {
            this.msgEl.scrollTop = this.msgEl.scrollHeight;
        });
    },

    hideTyping() {
        const t = document.getElementById('typing-indicator');
        if (t) t.remove();
        this.isBusy = false;
    }
};

window.UI = UI;
