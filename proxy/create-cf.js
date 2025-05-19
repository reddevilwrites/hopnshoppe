// const axios = require('axios');

// const BASE_URL = "http://localhost:4502";
// const AUTH = {
//   username: "admin",
//   password: "admin"
// };

// const PRODUCT_MODEL_PATH = "/conf/wknd/settings/dam/cfm/models/product";
// const TARGET_FOLDER = "/api/assets/wknd/products";

// function generateProduct(i){
//     return{
//         name: `product-${String(i).padStart(3, "0")}`,
//         title: `Product #${i}`,
//         sku: `PRD${String(i).padStart(3, "0")}`,
//         description: `This is an API-generated product number ${i}.`,
//         price: 1000 + i * 10,
//         availability: i % 3 !== 0,
//         category: i % 2 === 0 ? "Electronics" : "Furniture",
//         imagePath: `/content/dam/wknd/products/product${i}.jpg`
//     }
// }

// async function createContentFragment(product) {
//     try {
//     const payload = {
//       "properties": {
//         "cq:model": PRODUCT_MODEL_PATH,
//         "tittle": product.name
//       },
//       "elements": {
//         "title":{
//             "value": product.title,
//             ":type": "text/html"
//         },
//         "sku": {
//             "value": product.sku
//         },
//         "description":{
//             "value": product.description,
//             ":type": "text/html"
//         },
//         "price": {
//             "value": product.price
//         },
//         "availability": {
//             "value": product.availability
//         },
//         "category": {
//             "value": product.category
//         },
//         "imagePath": {
//             "value": product.imagePath
//         }
//       }
//     };

//     const res = await axios.post(`${BASE_URL}${TARGET_FOLDER}/${product.name}`, payload, {
//       auth: AUTH,
//       headers: {
//         "Content-Type": "application/json"
//       }
//     });

//     console.log(`✅ Created: ${product.name} — Status: ${res.status}`);
//   } catch (err) {
//     console.error(`❌ Failed: ${product.name}`);
//     if (err.response) {
//       console.error(`Status: ${err.response.status}`, err.response.data);
//     } else {
//       console.error(err.message);
//     }
//   }
// }

// (async () => {
//   for (let i = 4; i <= 4; i++) {
//     const product = generateProduct(i);
//     await createContentFragment(product);
//   }
// })();