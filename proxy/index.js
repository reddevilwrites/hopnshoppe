const express = require('express');
const axios = require('axios');
const cors = require('cors');
const productRouter = require('./routes/products')


const API_KEY = process.env.API_KEY || "abc123xyzSecureKey";
const TARGET_URL = process.env.TARGET_URL || "http://host.docker.internal:8081/products";
const BACKEND_BASE = process.env.BACKEND_BASE || "http://host.docker.internal:8081";

const app = express();

app.use(cors({origin : 'http://localhost:5173'}))
app.use(express.json());

app.get('/api/products', async(req, res) => {
    const token = req.get('Authorization');
    try {
        const response = await axios.get(TARGET_URL, {
            headers: {
                'Authorization' : token
            }
        });
        res.status(response.status).json(response.data)
    } catch (error) {
        console.error('Proxy error:', error.message);
        res.status(502).json({ error: 'Proxy failed', details: error.message });
    }
});

app.use('/api/products', productRouter);

app.get('/api/cart', async (req, res) => {
    const token = req.get('Authorization');
    if (!token) return res.status(401).json({ error: 'Unauthorized' });
    try {
        const response = await axios.get(`${BACKEND_BASE}/cart`, {
            headers: { Authorization: token }
        });
        res.status(response.status).json(response.data);
    } catch (error) {
        console.error('Proxy cart error (GET):', error.message);
        const status = error.response?.status || 502;
        res.status(status).json({ error: 'Proxy failed', details: error.message });
    }
});

app.post('/api/cart/:sku', async (req, res) => {
    const token = req.get('Authorization');
    if (!token) return res.status(401).json({ error: 'Unauthorized' });
    const { sku } = req.params;
    const queryString = new URLSearchParams(req.query).toString();
    const url = `${BACKEND_BASE}/cart/${encodeURIComponent(sku)}${queryString ? `?${queryString}` : ''}`;
    try {
        const response = await axios.post(url, req.body || {}, {
            headers: { Authorization: token }
        });
        res.status(response.status).json(response.data);
    } catch (error) {
        console.error('Proxy cart error (POST):', error.message);
        const status = error.response?.status || 502;
        res.status(status).json({ error: 'Proxy failed', details: error.message });
    }
});

app.post('/api/cart/:sku/increment', async (req, res) => {
    const token = req.get('Authorization');
    if (!token) return res.status(401).json({ error: 'Unauthorized' });
    const { sku } = req.params;
    try {
        const response = await axios.post(`${BACKEND_BASE}/cart/${encodeURIComponent(sku)}/increment`, req.body || {}, {
            headers: { Authorization: token }
        });
        res.status(response.status).json(response.data);
    } catch (error) {
        console.error('Proxy cart error (INC):', error.message);
        const status = error.response?.status || 502;
        res.status(status).json({ error: 'Proxy failed', details: error.message });
    }
});

app.post('/api/cart/:sku/decrement', async (req, res) => {
    const token = req.get('Authorization');
    if (!token) return res.status(401).json({ error: 'Unauthorized' });
    const { sku } = req.params;
    try {
        const response = await axios.post(`${BACKEND_BASE}/cart/${encodeURIComponent(sku)}/decrement`, req.body || {}, {
            headers: { Authorization: token }
        });
        res.status(response.status).json(response.data);
    } catch (error) {
        console.error('Proxy cart error (DEC):', error.message);
        const status = error.response?.status || 502;
        res.status(status).json({ error: 'Proxy failed', details: error.message });
    }
});

app.delete('/api/cart/:sku', async (req, res) => {
    const token = req.get('Authorization');
    if (!token) return res.status(401).json({ error: 'Unauthorized' });
    const { sku } = req.params;
    try {
        const response = await axios.delete(`${BACKEND_BASE}/cart/${encodeURIComponent(sku)}`, {
            headers: { Authorization: token }
        });
        res.status(response.status).json(response.data);
    } catch (error) {
        console.error('Proxy cart error (DELETE):', error.message);
        const status = error.response?.status || 502;
        res.status(status).json({ error: 'Proxy failed', details: error.message });
    }
});

app.listen(3000, () => {
    console.log('Node proxy running on http://localhost:3000')
})
