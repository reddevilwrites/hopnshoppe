const express = require('express')
const axios = require('axios');
const router = express.Router();


const BACKEND_BASE = 'http://host.docker.internal:8081';

router.get("/:sku", async (req, res) => {
    const {sku} = req.params;
    console.log(sku);
    const token = req.get('Authorization');

    try {
        const response = await axios.get(`${BACKEND_BASE}/products/${encodeURIComponent(sku)}`,{
            headers: {
                'Authorization': token
            }
        });
        res.json(response.data);
    } catch (err) {
        // 4) Error handling
    if (err.response) {
      // Backend returned a non-2xx status
      res
        .status(err.response.status)
        .json({ error: err.response.data || 'Upstream error' });
    } else {
      // Network / Axios issue
      console.error('Error fetching product by SKU:', err.message);
      res.status(500).json({ error: 'Server error' });
    }
    }
})

module.exports = router;