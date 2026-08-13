const SearchEngine = {
    faculty: [],
    rooms: [],
    sections: [],
    ragDB: new window.VectorStore(),
    GROQ_KEY: 'YOUR_GROQ_API_KEY_HERE',

    // ── Conversation Memory ──
    chatHistory: [],     // stores last N messages [{role, content}]
    _lastEntity: null,   // last discussed faculty/section name
    _lastSection: null,  // last discussed section object
    MAX_HISTORY: 6,      // keep last 6 messages for context

    _addToHistory(role, content) {
        this.chatHistory.push({ role, content: content.substring(0, 300) });
        if (this.chatHistory.length > this.MAX_HISTORY) this.chatHistory.shift();
    },

    /* Resolve pronouns using last discussed entity */
    _resolvePronouns(input) {
        const pronouns = /\b(she|he|they|her|his|him|this teacher|that teacher|this person|that person|this faculty|that faculty|this sir|this mam|this madam|that sir|that mam)\b/i;
        if (pronouns.test(input) && this._lastEntity) {
            const resolved = input.replace(pronouns, this._lastEntity);
            console.log(`[Pronoun resolved] "${input}" → "${resolved}"`);
            return resolved;
        }
        return input;
    },

    /* Track entity from a matched result */
    _trackEntity(name, section) {
        if (name) this._lastEntity = name;
        if (section) {
            this._lastSection = section;
            this._lastEntity = section.classTeacher.name.split('(')[0].trim();
        }
    },

    async init() {
        try {
            const [f, r, s] = await Promise.all([
                fetch('data/faculty.json').then(res => res.json()),
                fetch('data/rooms.json').then(res => res.json()),
                fetch('data/sections.json').then(res => res.json())
            ]);
            this.faculty = f;
            this.rooms = r;
            this.sections = s;
            this._buildRAG();
            return true;
        } catch (e) {
            console.error("Failed to load data:", e);
            return false;
        }
    },

    async callGroq(query, context) {
        const url = 'https://api.groq.com/openai/v1/chat/completions';
        const systemPrompt =
`You are "Campus Connect" — the official AI assistant for UEM Kolkata campus ONLY.

## YOUR DATA SOURCE:
You may ONLY use the [CAMPUS DATA] section below. This is your COMPLETE knowledge.

## STRICT RULES — FOLLOW WITHOUT EXCEPTION:
1. If the answer is NOT found in [CAMPUS DATA], reply EXACTLY:
   "😔 I don't have that information in my campus data. Please check the notice board."
2. NEVER use your training knowledge. NEVER guess. NEVER invent room numbers, names, dates, or contacts.
3. NEVER answer questions about celebrities, sports, maths, coding, history, politics, or anything outside UEM Kolkata campus.
4. If unsure, ALWAYS say you don't know rather than guessing.

## FORMAT:
• Use **bold** for room numbers, names, and key values.
• Keep replies concise (3-5 lines max).
• For sections: mention Block, Floor, Room, Teacher, Phone.
• For faculty: mention Name, Department, Cabin, Code.
• For rooms/places: mention Building, Floor, Room Number.

[CAMPUS DATA]
${context}`;

        try {
            const response = await fetch(url, {
                method: 'POST',
                headers: {
                    'Authorization': `Bearer ${this.GROQ_KEY}`,
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({
                    model: 'llama-3.3-70b-versatile',
                    messages: [
                        { role: 'system', content: systemPrompt },
                        ...this.chatHistory.slice(-4), // include recent history
                        { role: 'user', content: query }
                    ],
                    temperature: 0,
                    max_tokens: 400
                })
            });
            if (!response.ok) {
                console.error('Groq HTTP error:', response.status);
                return null;
            }
            const data = await response.json();
            if (!data.choices || !data.choices[0]) return null;
            return data.choices[0].message.content;
        } catch (e) {
            console.error("Groq Error:", e);
            return null;
        }
    },

    _buildRAG() {
        this.rooms.forEach(r => {
            this.ragDB.addDoc(`${r.use} is in ${r.bld}, ${r.floor}, Room ${r.room}`, { type: 'room', ...r });
        });
        this.faculty.forEach(f => {
            this.ragDB.addDoc(`${f.name} (${f.code}) is in ${f.dept} dept. Cabin: ${f.room}`, { type: 'faculty', ...f });
        });
        this.sections.forEach(s => {
            const t = s.classTeacher;
            const mentors = (s.mentors || []).join(', ');
            this.ragDB.addDoc(
                `Section ${s.section} is in ${s.block}, ${s.floor}, Room ${s.room}. Teacher: ${t.name}, Phone: ${t.phone}. Mentors: ${mentors}`,
                { type: 'section', ...s }
            );
        });
    },

    norm(s) { return s.toLowerCase().replace(/[.\-\/]/g, ' ').replace(/\s+/g, ' ').trim(); },

    /* Direct keyword match — bypasses TF-IDF IDF deflation for common words */
    _directSearch(input) {
        const q = this.norm(input);
        const words = q.split(' ').filter(w => w.length > 2);
        if (!words.length) return [];

        function score(text) {
            const t = text.toLowerCase().replace(/[.\-\/]/g, ' ');
            return words.filter(w => t.includes(w)).length / words.length;
        }

        // Rooms (lower threshold — "electrical lab" should match)
        const roomHits = this.rooms
            .map(r => ({ score: score(r.use + ' ' + r.bld + ' ' + r.room), data: r, type: 'room' }))
            .filter(x => x.score >= 0.4)
            .sort((a, b) => b.score - a.score)
            .slice(0, 3);

        // Faculty
        const facHits = this.faculty
            .map(f => ({ score: score(f.name + ' ' + f.dept + ' ' + (f.code || '')), data: f, type: 'faculty' }))
            .filter(x => x.score >= 0.5)
            .sort((a, b) => b.score - a.score)
            .slice(0, 3);

        // Prefer rooms for "where is" queries
        if (roomHits.length) return roomHits;
        return facHits;
    },

    /* Build plain-text context for the AI from relevant data */
    _buildContext(input) {
        const lines = [];

        // Always include sections (compact)
        lines.push("=== SECTIONS ===");
        this.sections.forEach(s => {
            const t = s.classTeacher;
            const mentors = (s.mentors || []).join(', ');
            lines.push(`Section ${s.section}: ${s.block}, ${s.floor}, Room ${s.room} | Teacher: ${t.name}, Phone: ${t.phone} | Mentors: ${mentors}`);
        });

        // Top RAG hits
        const rag = this.ragDB.search(input, 8);
        if (rag.length) {
            lines.push("\n=== RELEVANT MATCHES ===");
            rag.forEach(r => lines.push(r.text));
        }

        // Direct keyword hits
        const direct = this._directSearch(input);
        if (direct.length) {
            lines.push("\n=== DIRECT MATCHES ===");
            direct.forEach(d => {
                if (d.type === 'room') lines.push(`${d.data.use}: ${d.data.bld}, ${d.data.floor}, Room ${d.data.room}`);
                if (d.type === 'faculty') lines.push(`${d.data.name} | Dept: ${d.data.dept} | Cabin: ${d.data.room || 'Not recorded'}`);
            });
        }

        return lines.join('\n').substring(0, 5000);
    },

    async findResponse(rawInput) {
        // Resolve pronouns first
        const input = this._resolvePronouns(rawInput);
        this._addToHistory('user', rawInput);

        const q = this.norm(input);
        const words = q.split(' ').filter(w => w.length > 2);

        // 1. Greetings
        if (/^(hi|hello|hey|good\s*(morning|afternoon|evening)|start|help)$/.test(q)) {
            return "👋 Hi! I'm <strong>Campus Connect</strong>. I can help you find <strong>sections</strong>, <strong>faculty cabins</strong>, and <strong>room locations</strong> at UEM Kolkata!";
        }

        // 2. Section match — catch "section A", "class teacher of section A", "mentor of sec G", etc.
        const secMatch = input.match(/section\s*([A-P])\b/i)
                      || input.match(/\bsec\s+([A-P])\b/i)
                      || (q.match(/\b(teacher|mentor|class)\b/) && q.match(/\b([a-p])\b/i) && q.match(/\b([a-p])\b/i)[1].length === 1
                          ? [null, q.match(/\b([a-p])\b/i)[1]] : null);
        if (secMatch) {
            const letter = secMatch[1].toUpperCase();
            const s = this.sections.find(x => x.section === letter);
            if (s) {
                // If asking specifically about teacher
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
                // If asking specifically about mentors
                if (/mentor/i.test(input)) {
                    const mentors = (s.mentors || []);
                    if (mentors.length) {
                        return `🧑‍🏫 Mentors of <strong>Section ${s.section}</strong>:<br><br>` +
                               mentors.map(m => `▸ <strong>${m}</strong>`).join('<br>') +
                               `<br><br>📍 Room: <strong>${s.room}</strong> (${s.block}, ${s.floor})`;
                    }
                    return `😔 No mentors recorded for Section ${s.section}. Please check the notice board.`;
                }
                // General section query — show everything
                this._trackEntity(null, s);
                const reply = this._formatSection(s);
                this._addToHistory('assistant', reply);
                return reply;
            }
        }

        // 3. Faculty name match (skip generic words that cause flooding)
        const skipWords = new Set(['prof', 'dr', 'sir', 'mam', 'madam', 'teacher', 'class', 'mentor',
                                    'department', 'where', 'find', 'who', 'show', 'all', 'the', 'is',
                                    'section', 'room', 'cabin', 'what', 'tell', 'about', 'list']);
        const nameResults = this.faculty.filter(f => {
            const fName = this.norm(f.name);
            return words.some(w => fName.includes(w) && !skipWords.has(w));
        });
        if (nameResults.length > 0 && nameResults.length < 4) {
            this._trackEntity(nameResults[0].name, null);
            const reply = nameResults.map(f => this._formatFaculty(f)).join('<hr>');
            this._addToHistory('assistant', reply);
            return reply;
        }


        // 4. Room number match
        const roomMatch = input.match(/\b(B[123][\s\-]?(?:LG[\s\-]?)?\d+\.?\d*(?:\s*\([AB]\))?)\b/i);
        if (roomMatch) {
            const key = this.norm(roomMatch[1]);
            const r = this.rooms.filter(x => this.norm(x.room).includes(key));
            if (r.length) return r.map(x => this._formatRoom(x)).join('<hr>');
        }

        // 5. Direct keyword search (fixes "electrical lab" etc.)
        const directHits = this._directSearch(input);
        if (directHits.length) {
            const parts = directHits.map(d => {
                if (d.type === 'room') return this._formatRoom(d.data);
                if (d.type === 'faculty') return this._formatFaculty(d.data);
                return '';
            }).filter(Boolean);
            if (parts.length) return parts.join('<hr>');
        }

        // 6. AI with full context
        const context = this._buildContext(input);
        const aiResponse = await this.callGroq(input, context);
        if (aiResponse) {
            const reply = this._formatAI(aiResponse);
            this._addToHistory('assistant', reply);
            return reply;
        }

        // 7. Final fallback
        const campusKeywords = ['section', 'room', 'block', 'floor', 'teacher', 'faculty', 'mentor', 'cabin', 'where', 'find', 'who', 'list', 'dept', 'library', 'cafeteria', 'gym', 'office', 'lab'];
        if (campusKeywords.some(kw => q.includes(kw))) {
            return "🤔 I couldn't find a precise match. Could you be more specific? (e.g., <em>'Where is Section G?'</em> or <em>'Electrical lab room'</em>)";
        }

        return "😔 I only know about UEM Kolkata campus. Please check the notice board for other information.";
    },

    /* Markdown-to-HTML for AI responses */
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
               (mentors ? `<hr>🧑‍🏫 Mentors: ${mentors}` : '');
    },

    _formatRoom(r) {
        return `🏢 <strong>${r.use}</strong><br>📍 <strong>${r.bld}</strong>, ${r.floor}<br>🚪 Room: <strong>${r.room}</strong>`;
    },

    _formatFaculty(f) {
        return `<strong>${f.name}</strong> <span class="dept-tag">${f.dept}</span>${f.code ? `<span class="dept-tag">🏷 ${f.code}</span>` : ''}<br>🚪 Cabin: <strong>${f.room || 'Not recorded — check notice board'}</strong>`;
    }
};

window.SearchEngine = SearchEngine;
