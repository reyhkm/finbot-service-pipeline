import os
import json
import yfinance as yf
from datetime import datetime
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from google import genai
from google.genai import types

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

gemini_key = os.environ.get("GEMINI_API_KEY", "")
try:
    client = genai.Client(api_key=gemini_key) if gemini_key else None
except Exception:
    client = None

user_sessions = {}

class AIResponseSchema(BaseModel):
    tipe_respons: str = Field(
        description="Pilih 'grafik' jika data chart tersedia. Pilih 'teks_biasa' jika user hanya menyapa, bertanya identitas, atau data bursa tidak ditemukan."
    )
    pesan_teks: str = Field(
        description="Isi jawabanmu. Jika tipe 'grafik', ini adalah kalimat pengantar. Jika tipe 'teks_biasa', ini adalah jawaban lengkapmu."
    )

def pastikan_saham_indo(ticker: str) -> str:
    ticker = ticker.upper().strip()
    if ticker in ["IHSG", "JKSE", "COMPOSITE", "^JKSE"]:
        return "^JKSE"
    return ticker if ticker.endswith('.JK') else f"{ticker}.JK"

def generate_dynamic_chart(tickers: list, start_date: str = None, end_date: str = None) -> dict:
    try:
        datasets = []
        all_dates_set = set()
        saham_data_dict = {}
        
        for ticker in tickers:
            t_indo = pastikan_saham_indo(ticker)
            saham = yf.Ticker(t_indo)
            
            hist = None
            if start_date and end_date:
                try:
                    hist = saham.history(start=start_date, end=end_date)
                except Exception:
                    hist = None
            
            if hist is None or hist.empty:
                hist = saham.history(period="1mo")
            if hist is None or hist.empty:
                hist = saham.history(period="3mo")
            if hist is None or hist.empty:
                hist = saham.history(period="6mo")
                
            if hist is None or hist.empty:
                continue
                
            hist = hist.dropna(subset=['Close'])
            if hist.empty:
                continue
            
            dates_str = hist.index.strftime('%Y-%m-%d').tolist()
            all_dates_set.update(dates_str)
            
            harga_awal = hist['Close'].iloc[0]
            if harga_awal == 0:
                continue
            persentase_growth = ((hist['Close'] - harga_awal) / harga_awal) * 100
            
            if t_indo == "^JKSE":
                nama_perusahaan = "IHSG (Indeks Pasar)"
            else:
                try:
                    nama_perusahaan = saham.info.get('shortName', t_indo)
                except Exception:
                    nama_perusahaan = t_indo
            
            saham_data_dict[nama_perusahaan] = dict(zip(dates_str, persentase_growth.tolist()))
            
        if not saham_data_dict:
            return {
                "summary_untuk_ai": "Data bursa sedang tidak tersedia karena hari libur atau penyesuaian jam perdagangan.",
                "chart_data": None
            }
            
        sorted_labels = sorted(list(all_dates_set))
        
        for nama_perusahaan, data_harian in saham_data_dict.items():
            data_list = []
            for tgl in sorted_labels:
                data_list.append(data_harian.get(tgl, None))
                
            datasets.append({
                "label": nama_perusahaan,
                "data": data_list
            })
            
        return {
            "summary_untuk_ai": f"Grafik perbandingan {len(tickers)} saham/indeks berhasil dibuat.",
            "chart_data": {
                "labels": sorted_labels,
                "datasets": datasets
            }
        }
    except Exception as e:
        return {"summary_untuk_ai": f"Error pengolahan data: {str(e)}", "chart_data": None}

def jawab_pertanyaan_umum(pertanyaan: str) -> dict:
    return {"status": "sukses", "summary_untuk_ai": "Silakan jawab pertanyaan user secara natural."}

tools_config = [
    {
        "type": "function", "name": "generate_dynamic_chart", 
        "description": "PILIH TOOL INI JIKA: Pengguna meminta melihat grafik, chart, atau membandingkan pergerakan harga saham dan/atau IHSG.", 
        "parameters": {
            "type": "object", 
            "properties": {
                "tickers": {
                    "type": "array", 
                    "items": {"type": "string"},
                    "description": "Daftar kode saham atau IHSG (MAKSIMAL 5 SAHAM, contoh: ['BBCA', 'IHSG', 'GOTO'])"
                }, 
                "start_date": {
                    "type": "string", 
                    "description": "Tanggal mulai (YYYY-MM-DD)."
                },
                "end_date": {
                    "type": "string", 
                    "description": "Tanggal akhir (YYYY-MM-DD)."
                }
            }, 
            "required": ["tickers"]
        }
    },
    {
        "type": "function", "name": "jawab_pertanyaan_umum", 
        "description": "PILIH TOOL INI JIKA: Pengguna hanya menyapa (Halo, Hai), bertanya identitas (Siapa kamu?), atau bertanya hal di luar grafik saham.", 
        "parameters": {"type": "object", "properties": {"pertanyaan": {"type": "string"}}, "required": ["pertanyaan"]}
    }
]

class ChatRequest(BaseModel):
    user_id: str
    message: str

SYSTEM_PROMPT = """Kamu adalah Fina, Asisten Visualisasi Data Saham BEI. 

ATURAN UNIVERSAL PENENTUAN TANGGAL & WAKTU (WAJIB BERPIKIR SEBELUM PANGGIL TOOL):
1. Selalu gunakan [INFO SISTEM: Tanggal hari ini adalah YYYY-MM-DD] sebagai acuan dasar perhitunganmu.
2. SEGALANYA HARUS DITERJEMAHKAN MENJADI TANGGAL PRESISI (YYYY-MM-DD) untuk `start_date`:
   - HARIAN / MINGGUAN / BULANAN: Hitung matematis mundur dari tanggal hari ini.
   - IPO PERUSAHAAN: Gunakan tanggal IPO saham tersebut (misal GOTO: 2022-04-11).
   - HARI LIBUR / PERISTIWA KEAGAMAAN: Gunakan tanggal perkiraan hari H tersebut.
   - PERISTIWA SEJARAH / POLITIK / EKONOMI: Gunakan tanggal peristiwa tersebut (misal Pemilu 2024: 2024-02-14, Covid RI: 2020-03-02).
   - PERIODE KALENDER: Gunakan YYYY-01-01 atau YYYY-MM-01.
3. Jika pengguna SAMA SEKALI TIDAK menyebutkan rentang waktu, hitung start_date otomatis sebagai 3 bulan yang lalu dari tanggal hari ini.
4. Jika pengguna tidak menyebutkan tanggal akhir, otomatis paksa end_date dengan TANGGAL HARI INI.

ATURAN UNIVERSAL RESPONS SETELAH TOOL DILAKSANAKAN (ANTI-BLANK):
1. Setelah fungsi generate_dynamic_chart berhasil dijalankan, berikan respons JSON dengan tipe_respons: 'grafik' dan pesan_teks berupa kalimat pengantar yang ramah dan kontekstual.
2. Sebutkan nama saham/indeks serta tanggal/peristiwa/rentang waktu yang dicari pengguna di dalam pesan_teks.
3. DILARANG MENGEMBALIKAN TEKS KOSONG ATAU TANDA BACA SAJA!

ATURAN MUTLAK LAINNYA:
1. Kamu bisa memproses saham Indonesia maupun Indeks IHSG (gunakan ticker 'IHSG' atau '^JKSE').
2. BATAS MAKSIMAL SAHAM: Maksimal HANYA 5 saham/indeks dalam satu kali permintaan demi keterbacaan grafik. Jika lebih, ambil 5 saham pertama saja.
3. JANGAN PERNAH memvalidasi ketersediaan saham pakai ingatanmu. Teruskan ke tool generate_dynamic_chart.
4. Jika ditanya identitas, jawab: 'Saya Fina, asisten AI yang bertugas menampilkan grafik historis saham di Bursa Efek Indonesia.'
5. DILARANG memprediksi harga. Jawab HANYA menggunakan skema JSON yang diminta."""

@app.get("/")
def health_check():
    return {"status": "Fina Charting Engine (IHSG + IPO Bypass + Time Range Support) is Running!"}

@app.post("/chat")
async def chat_endpoint(req: ChatRequest):
    user_id = req.user_id
    user_message = req.message
    prev_interaction_id = user_sessions.get(user_id)

    today_date = datetime.now().strftime("%Y-%m-%d")

    if not prev_interaction_id:
        user_message = f"{SYSTEM_PROMPT}\n\n[INFO SISTEM: Tanggal hari ini adalah {today_date}]\n\nPertanyaan: {user_message}"
    else:
        user_message = f"[INFO SISTEM: Tanggal hari ini adalah {today_date}]\n\nPertanyaan: {user_message}"

    extracted_chart_data = None

    json_response_format = {
        "type": "text",
        "mime_type": "application/json",
        "schema": AIResponseSchema.model_json_schema()
    }

    try:
        if not client:
            raise ValueError("Gemini Client not initialized")

        interaction = client.interactions.create(
            model="gemini-3.1-flash-lite",
            input=user_message,
            tools=tools_config,
            previous_interaction_id=prev_interaction_id,
            generation_config={"temperature": 0.0, "thinking_level": "low"},
            response_format=json_response_format
        )

        for step in interaction.steps:
            if step.type == "function_call":
                if step.name == "generate_dynamic_chart":
                    tickers = step.arguments.get("tickers", [])
                    start_date = step.arguments.get("start_date")
                    end_date = step.arguments.get("end_date")
                    
                    hasil = generate_dynamic_chart(tickers, start_date, end_date)
                    if "chart_data" in hasil and hasil["chart_data"] is not None:
                        extracted_chart_data = hasil.pop("chart_data")
                    data_untuk_ai = hasil
                
                elif step.name == "jawab_pertanyaan_umum":
                    hasil = jawab_pertanyaan_umum(step.arguments.get("pertanyaan"))
                    data_untuk_ai = hasil
                else: 
                    continue
                
                interaction = client.interactions.create(
                    model="gemini-3.1-flash-lite",
                    previous_interaction_id=interaction.id,
                    tools=tools_config,
                    generation_config={"temperature": 0.0, "thinking_level": "low"},
                    response_format=json_response_format,
                    input=[{"type": "function_result", "name": step.name, "call_id": step.id, "result": [{"type": "text", "text": json.dumps(data_untuk_ai)}]}]
                )

        user_sessions[user_id] = interaction.id
        
        raw_output = interaction.output_text
        try:
            ai_json_response = json.loads(raw_output)
        except Exception:
            ai_json_response = {
                "tipe_respons": "grafik" if extracted_chart_data else "teks_biasa",
                "pesan_teks": raw_output if raw_output.strip() else "Berikut grafik pergerakan saham yang diminta."
            }
        
        return {
            "ai_response": ai_json_response,
            "chart_data": extracted_chart_data
        }

    except Exception as e:
        return {
            "ai_response": {
                "tipe_respons": "teks_biasa",
                "pesan_teks": "Maaf, data bursa sedang disinkronisasi. Silakan ulangi kueri beberapa saat lagi."
            },
            "chart_data": None
        }
