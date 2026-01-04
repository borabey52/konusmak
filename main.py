import streamlit as st
import os
import json
import sqlite3
import pandas as pd
from datetime import datetime
import google.generativeai as genai
import time

# --- 1. SAYFA VE API AYARLARI ---
st.set_page_config(page_title="Akıllı Konuşma Sınavı", layout="wide", page_icon="🎓")

try:
    if "GOOGLE_API_KEY" in st.secrets:
        api_key = st.secrets["GOOGLE_API_KEY"]
        os.environ["GOOGLE_API_KEY"] = api_key
        genai.configure(api_key=api_key)
    else:
        api_key = st.sidebar.text_input("Google API Key:", type="password")
        if api_key:
            os.environ["GOOGLE_API_KEY"] = api_key
            genai.configure(api_key=api_key)
except Exception as e:
    st.error(f"API Hatası: {e}")

# --- 2. VERİTABANI ---
def init_db():
    conn = sqlite3.connect('okul_sinav.db')
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS sonuclar (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ad_soyad TEXT,
            sinif_no TEXT,
            konu TEXT,
            konusma_metni TEXT,
            puan_100luk INTEGER,
            detaylar TEXT,
            ses_yolu TEXT,
            tarih DATETIME
        )
    ''')
    conn.commit()
    conn.close()

def sonuc_kaydet(ad, no, konu, metin, puan, detaylar, ses_path):
    conn = sqlite3.connect('okul_sinav.db')
    c = conn.cursor()
    c.execute("INSERT INTO sonuclar (ad_soyad, sinif_no, konu, konusma_metni, puan_100luk, detaylar, ses_yolu, tarih) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
              (ad, no, konu, metin, puan, json.dumps(detaylar, ensure_ascii=False), ses_path, datetime.now()))
    conn.commit()
    conn.close()

# --- 3. EXCEL VE SES KAYDI ---
def konulari_getir():
    dosya_yolu = "konusma_konulari.xlsx"
    if not os.path.exists(dosya_yolu):
        # Dosya yoksa örnek oluştur
        data = {
            'Konu': ['Teknoloji Bağımlılığı', 'Doğa Sevgisi'],
            'Giriş': ['Bağımlılık tanımı', 'Doğanın önemi'],
            'Gelişme': ['Zararları ve etkileri', 'İnsana faydaları'],
            'Sonuç': ['Çözüm yolları', 'Koruma yöntemleri']
        }
        pd.DataFrame(data).to_excel(dosya_yolu, index=False)
    
    try:
        df = pd.read_excel(dosya_yolu, engine='openpyxl')
        df.columns = df.columns.str.strip()
        konu_sozlugu = {}
        for index, row in df.iterrows():
            konu_sozlugu[row['Konu']] = {
                'Giriş': row['Giriş'], 'Gelişme': row['Gelişme'], 'Sonuç': row['Sonuç']
            }
        return konu_sozlugu
    except:
        return {}

def sesi_kalici_kaydet(audio_bytes, ad_soyad):
    klasor = "ses_kayitlari"
    if not os.path.exists(klasor):
        os.makedirs(klasor)
    tarih = datetime.now().strftime("%Y%m%d_%H%M%S")
    temiz_ad = "".join([c if c.isalnum() else "_" for c in ad_soyad]).strip("_")
    dosya_adi = f"{temiz_ad}_{tarih}.wav"
    dosya_yolu = os.path.join(klasor, dosya_adi)
    with open(dosya_yolu, "wb") as f:
        f.write(audio_bytes)
    return dosya_yolu

# --- 4. YAPAY ZEKA ANALİZİ ---
def sesi_dogrudan_analiz_et(audio_bytes, konu, detaylar, status_container):
    try:
        model = genai.GenerativeModel('gemini-1.5-flash')
        
        status_container.update(label="Ses işleniyor...", state="running")
        temp_filename = "temp_ses.wav"
        with open(temp_filename, "wb") as f:
            f.write(audio_bytes)
        
        status_container.update(label="Analiz ediliyor...", state="running")
        audio_file = genai.upload_file(temp_filename)
        
        while audio_file.state.name == "PROCESSING":
            time.sleep(0.5)
            audio_file = genai.get_file(audio_file.name)
            
        status_container.update(label="Puan hesaplanıyor...", state="running")
        
        prompt = f"""
        Sen bir Türkçe öğretmenisin.
        SINAV KONUSU: {konu}
        BEKLENEN PLAN: {detaylar['Giriş']}, {detaylar['Gelişme']}, {detaylar['Sonuç']}
        
        GÖREV:
        1. Transkripti çıkar.
        2. Kriterlere 1-3 arası puan ver (3:İyi, 2:Orta, 1:Zayıf).
        3. Puanı hesapla: (Toplam Puan / 12) * 100
        
        KRİTERLER: İçerik, Düzen, Dil, Akıcılık.
        
        JSON ÇIKTISI VER:
        {{
            "transkript": "...",
            "kriter_puanlari": {{ "konu_icerik": 0, "duzen": 0, "dil": 0, "akicilik": 0 }},
            "yuzluk_sistem_puani": 0,
            "ogretmen_yorumu": "..."
        }}
        """
        response = model.generate_content([audio_file, prompt])
        
        try:
            audio_file.delete()
            os.remove(temp_filename)
        except:
            pass
            
        text = response.text.replace("```json", "").replace("```", "").strip()
        return json.loads(text)
    except Exception as e:
        return {"yuzluk_sistem_puani": 0, "transkript": "Hata", "ogretmen_yorumu": str(e)}

# --- 5. ARAYÜZ (GÖRSEL DÜZELTMELER BURADA) ---
init_db()

st.markdown("""<style>.block-container {padding-top: 1rem;}</style>""", unsafe_allow_html=True)

col_left, col_center, col_right = st.columns([1, 8, 1]) # Orta kısmı genişlettik

with col_center:
    st.title("🎤 Dijital Konuşma Sınavı")
    st.markdown("---")

    # Öğrenci Bilgileri
    c1, c2 = st.columns(2)
    with c1: ad_soyad = st.text_input("Öğrenci Adı Soyadı")
    with c2: sinif_no = st.text_input("Sınıf / Numara")
    
    st.markdown("<br>", unsafe_allow_html=True)

    # Konu Seçimi ve Plan Gösterimi
    konular = konulari_getir()
    secilen_konu = None
    
    if konular:
        secilen_konu = st.selectbox("Sınav Konusu:", list(konular.keys()), index=None, placeholder="Konu seçiniz...")
        
        if secilen_konu:
            detay = konular[secilen_konu]
            
            # --- DÜZELTME 1: KONUŞMA PLANI (Kutucuklu Tasarım) ---
            st.markdown(f"### 📋 {secilen_konu} - Konuşma Planı")
            k1, k2, k3 = st.columns(3)
            with k1:
                st.info(f"**1. GİRİŞ**\n\n{detay['Giriş']}")
            with k2:
                st.warning(f"**2. GELİŞME**\n\n{detay['Gelişme']}")
            with k3:
                st.success(f"**3. SONUÇ**\n\n{detay['Sonuç']}")
            # ----------------------------------------------------

    st.markdown("<br>", unsafe_allow_html=True)

    # --- DÜZELTME 2: PUANLAMA KRİTERLERİ (HTML Tablo Geri Geldi) ---
    rubric_html = """
    <style>
        .rubric-table {width: 100%; border-collapse: collapse; font-size: 0.9em; margin-bottom: 20px;}
        .rubric-table th {background-color: #f8f9fa; border: 1px solid #dee2e6; padding: 8px; text-align: left;}
        .rubric-table td {border: 1px solid #dee2e6; padding: 8px;}
        .rubric-header {background-color: #e9ecef; font-weight: bold;}
    </style>
    <h4>⚖️ Puanlama Kriterleri</h4>
    <table class="rubric-table">
        <tr>
            <th style="width: 20%;">Kriter</th>
            <th style="width: 65%;">Açıklama</th>
            <th style="width: 15%; text-align: center;">Puan (1-3)</th>
        </tr>
        <tr>
            <td class="rubric-header">1. İçerik</td>
            <td>Konuya hakimiyet, verilen plana (Giriş-Gelişme-Sonuç) uyum.</td>
            <td style="text-align: center;">1 - 3</td>
        </tr>
        <tr>
            <td class="rubric-header">2. Düzen</td>
            <td>Konuşmanın bütünlüğü, fikirlerin sıralanışı.</td>
            <td style="text-align: center;">1 - 3</td>
        </tr>
        <tr>
            <td class="rubric-header">3. Dil</td>
            <td>Kelime zenginliği ve dil bilgisi kurallarına uygunluk.</td>
            <td style="text-align: center;">1 - 3</td>
        </tr>
        <tr>
            <td class="rubric-header">4. Akıcılık</td>
            <td>Telaffuz, vurgu, tonlama ve akıcı anlatım.</td>
            <td style="text-align: center;">1 - 3</td>
        </tr>
    </table>
    """
    st.markdown(rubric_html, unsafe_allow_html=True)
    # ------------------------------------------------------------

    st.markdown("### 🎙️ Kaydı Başlat")
    ses_kaydi = st.audio_input("Mikrofona tıklayın")

    if ses_kaydi and secilen_konu:
        if st.button("Sınavı Bitir ve Puanla", type="primary", use_container_width=True):
            if not ad_soyad:
                st.warning("⚠️ Lütfen öğrenci ismini giriniz.")
            else:
                with st.status("Değerlendiriliyor...", expanded=True) as status:
                    # 1. Kayıt
                    audio_bytes = ses_kaydi.getvalue()
                    kayit_yolu = sesi_kalici_kaydet(audio_bytes, ad_soyad)
                    st.write(f"Ses arşivlendi: {kayit_yolu}")
                    
                    # 2. Analiz
                    sonuc = sesi_dogrudan_analiz_et(audio_bytes, secilen_konu, konular[secilen_konu], status)
                    
                    # 3. Veritabanı
                    puan = sonuc.get("yuzluk_sistem_puani", 0)
                    transkript = sonuc.get("transkript", "")
                    sonuc_kaydet(ad_soyad, sinif_no, secilen_konu, transkript, puan, sonuc, kayit_yolu)
                    
                    status.update(label="Tamamlandı!", state="complete", expanded=False)
                    st.balloons()

                    # SONUÇ EKRANI
                    st.markdown(f"""
                    <div style="background-color: #dcfce7; border: 2px solid #22c55e; border-radius: 12px; padding: 15px; text-align: center; margin-bottom: 20px;">
                        <h2 style="margin:0; color:#166534;">PUAN: {puan}</h2>
                    </div>
                    """, unsafe_allow_html=True)
                    
                    with st.container(border=True):
                        st.subheader("Sonuç Detayları")
                        st.info(f"**Öğretmen Yorumu:** {sonuc.get('ogretmen_yorumu')}")
                        st.text_area("Transkript", transkript, height=150)
                        
                        kp = sonuc.get("kriter_puanlari", {})
                        st.table(pd.DataFrame({
                            "Kriter": ["İçerik", "Düzen", "Dil", "Akıcılık"],
                            "Puan": [kp.get("konu_icerik",0), kp.get("duzen",0), kp.get("dil",0), kp.get("akicilik",0)]
                        }).set_index("Kriter"))
                        
                        st.audio(kayit_yolu)
