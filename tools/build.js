// GitHub Pages үшін index.html құрастыру: node tools/build.js
// app.html-ді толық HTML құжатына орайды (claude.ai артефакті мен tools/serve.js сияқты).
const fs = require("fs");
const path = require("path");

const root = path.resolve(__dirname, "..");
const body = fs.readFileSync(path.join(root, "app.html"), "utf8");
const page = `<!doctype html>
<html lang="kk">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="description" content="Profitability AI — ХҚТУ хакатоны, Кейс 01: білім беру бағдарламаларының табыстылығын есептеу және AI арқылы түсіндіру.">
<style>:root{color-scheme:light}body{margin:0;font:14px system-ui,sans-serif}img{max-width:100%}[hidden]{display:none!important}</style>
</head>
<body>
<!-- Бұл файлды қолмен өзгертпеңіз: app.html-ді түзетіп, node tools/build.js іске қосыңыз -->
${body}
</body>
</html>
`;
fs.writeFileSync(path.join(root, "index.html"), page);
console.log("index.html құрастырылды:", page.length, "таңба");
