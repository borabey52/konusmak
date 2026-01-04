import streamlit as st
import os
import json
import sqlite3
import pandas as pd
from datetime import datetime
import google.generativeai as genai
import time

# --- 2. AYARLAR (KESİN ÇÖZÜM) ---
try:
    if "GOOGLE_API_KEY" in st.secrets:
        api_key = st.secrets["GOOGLE_API_KEY"]
        # 1. Şifreyi İşletim Sistemine Tanıt (File API hatasını çözer)
        os.environ["GOOGLE_API_KEY"] = api_key
        # 2. Kütüphaneyi Yapılandır
        genai.configure(api_key=api_key)
    else:
        st.error("Lütfen Streamlit panelinden API Key ekleyin.")
except Exception as e:
    st.error(f"Ayarlar yüklenirken hata oluştu: {e}")

# --- 3. VERİTABANI ---
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
            tarih DATETIME
        )
    ''')
    conn.commit()
    conn.close()

def sonuc_kaydet(ad, no, konu, metin, puan, detaylar):
    conn = sqlite3.connect('okul_sinav.db')
    c = conn.cursor()
    c.execute("INSERT INTO sonuclar (ad_soyad, sinif_no, konu, konusma_metni, puan_100luk, detaylar, tarih) VALUES (?, ?, ?, ?, ?, ?, ?)",
              (ad, no, konu, metin, puan, json.dumps(detaylar, ensure_ascii=False), datetime.now()))
    conn.commit()
    conn.close()

# --- 4. EXCEL OKUMA ---
def konulari_getir():
    dosya_yolu = "konusma_konulari.xlsx"
    if not os.path.exists(dosya_yolu):
        return {}
    try:
        df = pd.read_excel(dosya_yolu, engine='openpyxl')
        df.columns = df.columns.str.strip()
        required_cols = ['Konu', 'Giriş', 'Gelişme', 'Sonuç']
        if all(col in df.columns for col in required_cols):
            df = df.dropna(subset=['Konu'])
            konu_sozlugu = {}
            for index, row in df.iterrows():
                konu_sozlugu[row['Konu']] = {
                    'Giriş': row['Giriş'], 'Gelişme': row['Gelişme'], 'Sonuç': row['Sonuç']
                }
            return konu_sozlugu
        return {}
    except Exception:
        return {}

# --- 5. SES ANALİZİ ---
def sesi_dogrudan_analiz_et(audio_bytes, konu, detaylar):
    try:
        # Model ismi
        model = genai.GenerativeModel('gemini-flash-latest')
        
        # 1. Sesi geçici bir dosya olarak kaydet
        temp_filename = "ogrenci_sesi.wav"
        with open(temp_filename, "wb") as f:
            f.write(audio_bytes)
        
        # 2. Dosyayı Gemini sunucularına yükle
        # (os.environ ayarı sayesinde artık hata vermez)
        audio_file = genai.upload_file(temp_filename)
        
        # Dosyanın işlenmesini bekle
        while audio_file.state.name == "PROCESSING":
            time.sleep(1)
            audio_file = genai.get_file(audio_file.name)
            
        # 3. Prompt Hazırla
        prompt = f"""
        Sen bir Türkçe öğretmenisin. Sana bir öğrencinin konuşma sınavı ses kaydını gönderiyorum.
        Lütfen bu sesi DİNLE ve değerlendir.
        
        SINAV KONUSU: {konu}
        BEKLENEN PLAN:
        - Giriş: {detaylar['Giriş']}
        - Gelişme: {detaylar['Gelişme']}
        - Sonuç: {detaylar['Sonuç']}
        
        GÖREVLERİN:
        1. Öğrencinin ne dediğini tam olarak yazıya dök (Transkript).
        2. Yazıya dökerken imla kurallarına göre düzelt.
        3. Ses tonunu, vurguları ve akıcılığı da dikkate alarak puanla.
        
        KRİTERLER (Her biri 1-3 Puan):
        1. Konu ve İçerik (Konuya hakim mi?)
        2. Düzen (Giriş-Gelişme-Sonuç var mı?)
        3. Dili Kullanma (Kelime dağarcığı)
        4. Akıcılık (Duraksamalar, "ııı"lamalar, tonlama, vurgu)
        
        SADECE JSON FORMATINDA CEVAP VER:
        {{
            "transkript": "Buraya öğrencinin konuşmasının metnini yaz.",
            "kriter_puanlari": {{ "konu_icerik": 2, "duzen": 2, "dil": 2, "akicilik": 2 }},
            "toplam_ham_puan": 8,
            "yuzluk_sistem_puani": 66,
            "ogretmen_yorumu": "Buraya yorumunu yaz."
        }}
        """
        
        # 4. Sesi ve Prompt'u beraber gönder
        response = model.generate_content([audio_file, prompt])
        
        # 5. Temizlik (Dosyayı sil)
        try:
            audio_file.delete()
            os.remove(temp_filename)
        except:
            pass
            
        text = response.text.replace("```json", "").replace("```", "")
        return json.loads(text)
        
    except Exception as e:
        return {"yuzluk_sistem_puani": 0, "transkript": "Analiz Hatası", "ogretmen_yorumu": f"Hata Detayı: {str(e)}"}

# --- 6. ARAYÜZ ---
st.set_page_config(page_title="Konuşma Sınavı", layout="wide", page_icon="🎓")
init_db()

st.markdown("""<style>.block-container {padding-top: 2rem; padding-bottom: 2rem;}</style>""", unsafe_allow_html=True)
col_left, col_center, col_right = st.columns([1, 2, 1])

with col_center:
    st.title("🎤 Dijital Konuşma Sınavı")
    st.markdown("---")

    c1, c2 = st.columns(2)
    with c1: ad_soyad = st.text_input("Adı Soyadı")
    with c2: sinif_no = st.text_input("Sınıf / Numara")
    
    st.markdown("<br>", unsafe_allow_html=True)
    
    konular = konulari_getir()
    secilen_konu = None
    
    if konular:
        secilen_konu = st.selectbox("Konu Seçiniz:", list(konular
