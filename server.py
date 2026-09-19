if path in ("/", "/index.html"):
            return self._file("templates/index.html", "text/html; charset=utf-8") if path in ("/", "/index.html"):
            html = """<!DOCTYPE html><html><head><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'><title>FOOTBALL ANALYST IA</title>
<style>body{margin:0;font-family:sans-serif;background:#08110c;color:#e8f5e9;padding:16px}input,button{width:100%;padding:12px;margin:6px 0;border:0;border-radius:10px;font-size:16px}button{background:#22c55e;font-weight:700}pre{white-space:pre-wrap;background:#0d1f16;padding:12px;border-radius:10px}</style></head>
<body><h1>⚽ FOOTBALL ANALYST IA</h1>
<input id=h placeholder=Mandante><input id=a placeholder=Visitante>
<input id=l placeholder=Campeonato><input id=d type=date>
<button id=b>ANALISAR JOGO ⚽</button><pre id=o>Preencha os times.</pre>
<script>
document.getElementById('d').value=new Date().toISOString().slice(0,10);
document.getElementById('b').onclick=async()=>{
const home=h.value.trim(),away=a.value.trim();
o.textContent='Coletando...';
const r=await fetch('/api/analyze',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({home,away,league:l.value,date:d.value})});
const j=await r.json();
o.textContent=j.ok?JSON.stringify(j.summary||j,null,2):(j.error||'erro');
};
</script></body></html>"""
            self.send_response(200)
            raw=html.encode('utf-8')
            self.send_header('Content-Type','text/html; charset=utf-8')
            self.send_header('Content-Length',str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)
            return
