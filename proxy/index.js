const express = require('express');
const axios = require('axios');
const cors = require('cors');
const productRouter = require('./routes/products')


const API_KEY = process.env.API_KEY || "abc123xyzSecureKey";
const TARGET_URL = process.env.TARGET_URL || "http://host.docker.internal:8081/products";

const app = express();

app.use(cors({origin : 'http://localhost:5173'}))

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

app.listen(3000, () => {
    console.log('Node proxy running on http://localhost:3000')
})
