import streamlit as st
import os
import json
import sqlite3
import pandas as pd
from datetime import datetime
import google.generativeai as genai
import time

# --- 1. SAYFA AYARLARI ---
st.set_page_config(page_title="Akıllı Konuşma Sınavı", layout="wide", page_icon="🎓")

# --- 2. API KEY AYARLARI ---
# Secrets'tan okumaya çalış, yoksa kullanıcıdan manuel iste (Hata almamak için)
try:
    if "GOOGLE_API_KEY" in st.secrets:
        api_key = st.secrets["GOOGLE_API_KEY"]
        os.environ["GOOGLE_API_KEY"] = api_key
        genai.configure(api_key=api_key)
    else:
        # Eğer secrets yoksa sidebar'dan girilmesine izin ver (Test amaçlı)
        api_key = st.sidebar.text_input("Google API Key Giriniz:", type="password")
        if api_key:
            os.environ["GOOGLE_API_KEY"] = api_key
            genai.configure(api_key=api_key)
except Exception as e:
    st.error(f"API Ayarlarında sorun var: {e}")

# --- 3. VERİTABANI İŞLEMLERİ ---
def init_db():
    conn = sqlite3.connect('okul_sinav.db')
    c = conn.cursor()
    # Tabloyu oluştur (ses_yolu sütunu eklendi)
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

# --- 4. DOSYA İŞLEMLERİ (EXCEL & SES KAYDI) ---
def konulari_getir():
    dosya_yolu = "konusma_konulari.xlsx"
    
    # Dosya yoksa otomatik örnek oluştur (Kullanıcı uğraşmasın diye)
    if not os.path.exists(dosya_yolu):
        data = {
            'Konu': ['Yapay Zeka', 'Küresel Isınma', 'Kitap Okumanın Önemi'],
            'Giriş': ['Yapay zeka nedir tanımı', 'İklim değişikliği tanımı', 'Okuma kültürü'],
            'Gelişme': ['Faydaları ve zararları', 'Sebepleri ve sonuçları', 'Bireysel gelişim'],
            'Sonuç': ['Gelecek öngörüsü', 'Çözüm önerileri', 'Tavsiyeler']
        }
        df_temp = pd.DataFrame(data)
        df_temp.to_excel(dosya_yolu, index=False)
    
    try:
        df = pd.read_excel(dosya_yolu, engine='openpyxl')
        df.columns = df.columns.str.strip()
        konu_sozlugu = {}
        for index, row in df.iterrows():
            konu_sozlugu[row['Konu']] = {
                'Giriş': row['Giriş'], 'Gelişme': row['Gelişme'], 'Sonuç': row['Sonuç']
            }
        return konu_sozlugu
    except Exception:
        return {}

def sesi_kalici_kaydet(audio_bytes, ad_soyad):
    # Klasör oluştur
    klasor = "ses_kayitlari"
    if not os.path.exists(klasor):
        os.makedirs(klasor)
    
    # Dosya ismi oluştur (Türkçe karakterleri temizle)
    tarih = datetime.now().strftime("%Y%m%d_%H%M%S")
    temiz_ad = "".join([c if c.isalnum() else "_" for c in ad_soyad]).strip("_")
    dosya_adi = f"{temiz_ad}_{tarih}.wav"
    dosya_yolu = os.path.join(klasor, dosya_adi)
    
    # Kaydet
    with open(dosya_yolu, "wb") as f:
        f.write(audio_bytes)
    return dosya_yolu

# --- 5. YAPAY ZEKA ANALİZİ ---
def sesi_dogrudan_analiz_et(audio_bytes, konu, detaylar, status_container):
    try:
        # Daha kararlı model seçimi
        model = genai.GenerativeModel('gemini-1.5-flash')
        
        status_container.update(label="Ses dosyası işleniyor...", state="running")
        temp_filename = "temp_ogrenci_sesi.wav"
        with open(temp_filename, "wb") as f:
            f.write(audio_bytes)
        
        status_container.update(label="Google'a yükleniyor...", state="running")
        audio_file = genai.upload_file(temp_filename)
        
        while audio_file.state.name == "PROCESSING":
            time.sleep(0.5)
            audio_file = genai.get_file(audio_file.name)
            
        status_container.update(label="Yapay zeka puanlıyor...", state="running")
        
        # Kesin Hesaplama İsteyen Prompt
        prompt = f"""
        Sen bir Türkçe öğretmenisin. Bu ses kaydını dürüstçe değerlendir.
        
        SINAV KONUSU: {konu}
        BEKLENEN PLAN: {detaylar['Giriş']}, {detaylar['Gelişme']}, {detaylar['Sonuç']}
        
        GÖREVLER:
        1. Ses kaydının transkriptini çıkar.
        2. Aşağıdaki 4 kriterin her birine 1, 2 veya 3 puan ver (3: İyi, 2: Orta, 1: Zayıf).
        3. Puanları topla ve formüle göre 100'lük sisteme çevir.
        
        KRİTERLER:
        - İçerik
        - Düzen
        - Dil
        - Akıcılık
        
        HESAPLAMA: (Toplam Puan / 12) * 100. (Örneğin toplam 9 ise sonuç 75 olmalı).
        
        JSON ÇIKTISI VER:
        {{
            "transkript": "...",
            "kriter_puanlari": {{ "konu_icerik": 0, "duzen": 0, "dil": 0, "akicilik": 0 }},
            "toplam_ham_puan": 0,
            "yuzluk_sistem_puani": 0,
            "ogretmen_yorumu": "..."
        }}
        """
        
        response = model.generate_content([audio_file, prompt])
        
        # Temizlik
        try:
            audio_file.delete()
            os.remove(temp_filename)
        except:
            pass
            
        text = response.text.replace("```json", "").replace("```", "").strip()
        return json.loads(text)
        
    except Exception as e:
        return {"yuzluk_sistem_puani": 0, "transkript": "Hata", "ogretmen_yorumu": f"Hata: {str(e)}"}

# --- 6. ARAYÜZ ---
init_db()

st.markdown("""<style>.block-container {padding-top: 1rem;}</style>""", unsafe_allow_html=True)

col_left, col_center, col_right = st.columns([1, 6, 1])

with col_center:
    st.title("🎤 Dijital Konuşma Sınavı")
    st.markdown("---")

    c1, c2 = st.columns(2)
    with c1: ad_soyad = st.text_input("Öğrenci Adı Soyadı")
    with c2: sinif_no = st.text_input("Sınıf / Numara")
    
    konular = konulari_getir()
    secilen_konu = None
    
    if konular:
        secilen_konu = st.selectbox("Sınav Konusu:", list(konular.keys()), index=None, placeholder="Konu seçiniz...")
        if secilen_konu:
            detay = konular[secilen_konu]
            with st.container(border=True):
                st.info(f"**Konu: {secilen_konu}**")
                st.markdown(f"**Beklenenler:** {detay['Giriş']} ➔ {detay['Gelişme']} ➔ {detay['Sonuç']}")
    
    st.markdown("<br>", unsafe_allow_html=True)
    
    # --- PUANLAMA KRİTERLERİ (Bilgi Amaçlı) ---
    with st.expander("ℹ️ Puanlama Kriterlerini Gör"):
        st.markdown("""
        | Kriter | Açıklama | Puan |
        |---|---|---|
        | **İçerik** | Konuya hakimiyet ve plana uyum | 1-3 |
        | **Düzen** | Giriş, gelişme, sonuç bütünlüğü | 1-3 |
        | **Dil** | Kelime zenginliği ve gramer | 1-3 |
        | **Akıcılık** | Telaffuz ve tonlama | 1-3 |
        """)

    st.markdown("### 🎙️ Sınavı Başlat")
    ses_kaydi = st.audio_input("Kayda başlamak için tıklayın")

    if ses_kaydi and secilen_konu:
        if st.button("Sınavı Bitir ve Değerlendir", type="primary", use_container_width=True):
            if not ad_soyad:
                st.warning("⚠️ Lütfen öğrenci bilgilerini giriniz.")
            else:
                # --- SÜREÇ BAŞLIYOR ---
                with st.status("Sınav değerlendiriliyor...", expanded=True) as status:
                    
                    # 1. Kaydı Al
                    audio_bytes = ses_kaydi.getvalue()
                    
                    # 2. Kalıcı Kaydet
                    try:
                        kayit_yolu = sesi_kalici_kaydet(audio_bytes, ad_soyad)
                        st.success(f"Ses kaydı arşivlendi: {kayit_yolu}")
                    except Exception as e:
                        st.error(f"Kayıt hatası: {e}")
                        kayit_yolu = "Kaydedilemedi"

                    # 3. Analiz Et
                    sonuc = sesi_dogrudan_analiz_et(audio_bytes, secilen_konu, konular[secilen_konu], status)
                    
                    transkript = sonuc.get("transkript", "")
                    puan = sonuc.get("yuzluk_sistem_puani", 0)
                    
                    # 4. Veritabanına Yaz
                    sonuc_kaydet(ad_soyad, sinif_no, secilen_konu, transkript, puan, sonuc, kayit_yolu)
                    
                    status.update(label="Değerlendirme Tamamlandı!", state="complete", expanded=False)
                    st.balloons()

                    # --- SONUÇ KARTI ---
                    st.markdown(f"""
                    <div style="background-color: #f0fdf4; border: 2px solid #22c55e; border-radius: 10px; padding: 20px; text-align: center; margin-top: 20px;">
                        <h3 style="margin:0; color:#166534;">BAŞARI PUANI</h3>
                        <h1 style="margin:0; color:#15803d; font-size: 5rem;">{puan}</h1>
                    </div>
                    """, unsafe_allow_html=True)
                    
                    # --- DETAYLAR ---
                    with st.container(border=True):
                        st.subheader("📝 Sınav Karnesi")
                        
                        col_a, col_b = st.columns([2, 1])
                        
                        with col_a:
                            st.markdown("**🗣️ Öğrenci Konuşması (Transkript):**")
                            st.text_area("", transkript, height=200, disabled=True)
                            
                            st.markdown("**💡 Öğretmen Yorumu:**")
                            st.info(sonuc.get('ogretmen_yorumu'))

                        with col_b:
                            st.markdown("**📊 Kriter Puanları**")
                            kp = sonuc.get("kriter_puanlari", {})
                            st.table(pd.DataFrame({
                                "Kriter": ["İçerik", "Düzen", "Dil", "Akıcılık"],
                                "Puan": [kp.get("konu_icerik",0), kp.get("duzen",0), kp.get("dil",0), kp.get("akicilik",0)]
                            }).set_index('Kriter'))
                            
                            st.markdown("**🎧 Kaydı Dinle:**")
                            st.audio(kayit_yolu)
