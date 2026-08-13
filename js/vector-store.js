class VectorStore {
    constructor() {
        this.docs = [];
        this.idf = {};
        this._dirty = true;
    }

    tokenize(text) {
        return text.toLowerCase()
            .replace(/[.\-\/]/g, ' ')
            .replace(/[^a-z0-9\s]/g, '')
            .split(/\s+/)
            .filter(w => w.length > 1);
    }

    addDoc(text, meta = {}) {
        const tokens = this.tokenize(text);
        const tf = {};
        tokens.forEach(t => { tf[t] = (tf[t] || 0) + 1; });
        const total = tokens.length || 1;
        Object.keys(tf).forEach(t => tf[t] /= total);
        this.docs.push({ text, meta, tf });
        this._dirty = true;
    }

    _buildIDF() {
        const N = this.docs.length;
        const df = {};
        this.docs.forEach(d => Object.keys(d.tf).forEach(t => { df[t] = (df[t] || 0) + 1; }));
        Object.keys(df).forEach(t => {
            this.idf[t] = Math.log((N + 1) / (df[t] + 1)) + 1;
        });
        this._dirty = false;
    }

    _tfidfVec(tf) {
        const v = {};
        Object.entries(tf).forEach(([t, w]) => { v[t] = w * (this.idf[t] || 0); });
        return v;
    }

    _cosine(a, b) {
        const keys = Object.keys(a).filter(k => b[k]);
        if (!keys.length) return 0;
        const dot = keys.reduce((s, k) => s + a[k] * b[k], 0);
        const na = Math.sqrt(Object.values(a).reduce((s, v) => s + v * v, 0));
        const nb = Math.sqrt(Object.values(b).reduce((s, v) => s + v * v, 0));
        return (na && nb) ? dot / (na * nb) : 0;
    }

    search(query, topK = 3) {
        if (this._dirty) this._buildIDF();
        const qTokens = this.tokenize(query);
        const qTF = {};
        qTokens.forEach(t => { qTF[t] = (qTF[t] || 0) + 1 / qTokens.length; });
        const qVec = this._tfidfVec(qTF);
        return this.docs
            .map((d, i) => ({ score: this._cosine(qVec, this._tfidfVec(d.tf)), idx: i }))
            .sort((a, b) => b.score - a.score)
            .slice(0, topK)
            .filter(r => r.score > 0.01)
            .map(r => ({ ...this.docs[r.idx], score: r.score }));
    }
}

window.VectorStore = VectorStore;
