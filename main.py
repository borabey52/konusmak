import streamlit as st
import os
import json
import sqlite3
import pandas as pd
from datetime import datetime
import google.generativeai as genai
import time

# --- 1. AYARLAR ---
st.set_page_config(page_title="Konuşma Sınavı Sistemi", layout="wide", page_icon="🎓")
ADMIN_SIFRESI = "1234"  # <-- YÖNETİCİ ŞİFRESİ BURADA

# API Key Kontrolü
try:
    if "GOOGLE_API_KEY" in st.secrets:
        os.environ["GOOGLE_API_KEY"] = st.secrets["GOOGLE_API_KEY"]
        genai.configure(api_key=st.secrets["GOOGLE_API_KEY"])
except Exception as e:
    pass

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

def tum_sonuclari_getir():
    """Admin paneli için tüm detayları getirir"""
    conn = sqlite3.connect('okul_sinav.db')
    df = pd.read_sql_query("SELECT * FROM sonuclar ORDER BY id DESC", conn)
    conn.close()
    return df

# --- 3. YARDIMCI FONKSİYONLAR ---
def konulari_getir():
    dosya_yolu = "konusma_konulari.xlsx"
    if not os.path.exists(dosya_yolu):
        data = {
            'Konu': ['Teknoloji', 'Spor'],
            'Giriş': ['Tanım', 'Önem'],
            'Gelişme': ['Faydalar', 'Türler'],
            'Sonuç': ['Gelecek', 'Özet']
        }
        pd.DataFrame(data).to_excel(dosya_yolu, index=False)
    
    try:
        df = pd.read_excel(dosya_yolu, engine='openpyxl')
        return {row['Konu']: {'Giriş': row['Giriş'], 'Gelişme': row['Gelişme'], 'Sonuç': row['Sonuç']} for i, row in df.iterrows()}
    except:
        return {}

def sesi_kalici_kaydet(audio_bytes, ad_soyad):
    klasor = "ses_kayitlari"
    if not os.path.exists(klasor): os.makedirs(klasor)
    tarih = datetime.now().strftime("%Y%m%d_%H%M%S")
    temiz_ad = "".join([c if c.isalnum() else "_" for c in ad_soyad]).strip("_")
    dosya_yolu = os.path.join(klasor, f"{temiz_ad}_{tarih}.wav")
    with open(dosya_yolu, "wb") as f: f.write(audio_bytes)
    return dosya_yolu

def sesi_analiz_et(audio_bytes, konu, detaylar, status_container):
    try:
        model = genai.GenerativeModel('gemini-flash-latest')
        status_container.update(label="Yapay Zeka Analiz Ediyor...", state="running")
        
        temp_file = "temp_ses.wav"
        with open(temp_file, "wb") as f: f.write(audio_bytes)
        
        audio_file = genai.upload_file(temp_file)
        while audio_file.state.name == "PROCESSING":
            time.sleep(0.5)
            audio_file = genai.get_file(audio_file.name)
            
        prompt = f"""
        Rol: Türkçe Öğretmeni.
        Konu: {konu}. Plan: {detaylar}.
        Görev:
        1. Transkript çıkar.
        2. Kriterleri (İçerik, Düzen, Dil, Akıcılık) 1-3 puanla.
        3. Puan = (Toplam/12)*100.
        
        JSON Çıktısı:
        {{ "transkript": "...", "kriter_puanlari": {{"konu_icerik":0,"duzen":0,"dil":0,"akicilik":0}}, "yuzluk_sistem_puani":0, "ogretmen_yorumu":"..." }}
        """
        response = model.generate_content([audio_file, prompt])
        try: os.remove(temp_file) 
        except: pass
        
        return json.loads(response.text.replace("```json","").replace("```","").strip())
    except Exception as e:
        return {"yuzluk_sistem_puani": 0, "transkript": "Hata", "ogretmen_yorumu": str(e)}

# --- 4. ARAYÜZ ---
init_db()

# Session State (Giriş Durumu İçin)
if 'admin_logged_in' not in st.session_state:
    st.session_state['admin_logged_in'] = False

# --- SOL PANEL (GİRİŞ VE MENÜ) ---
with st.sidebar:
    st.title("🔐 Yönetici Girişi")
    
    if not st.session_state['admin_logged_in']:
        sifre = st.text_input("Admin Şifresi", type="password")
        if st.button("Giriş Yap"):
            if sifre == ADMIN_SIFRESI:
                st.session_state['admin_logged_in'] = True
                st.success("Giriş Başarılı!")
                st.rerun()
            else:
                st.error("Hatalı Şifre")
    else:
        st.success("Yönetici Modu Aktif")
        secim = st.radio("Mod Seçiniz:", ["📝 Sınav Ekranı", "📂 Sonuç Arşivi (Admin)"])
        if st.button("Çıkış Yap"):
            st.session_state['admin_logged_in'] = False
            st.rerun()

# --- ANA EKRAN KONTROLÜ ---
# Eğer giriş yapılmadıysa veya "Sınav Ekranı" seçiliyse standart ekranı göster
if not st.session_state['admin_logged_in'] or (st.session_state['admin_logged_in'] and secim == "📝 Sınav Ekranı"):
    
    # --- STANDART SINAV EKRANI ---
    col_left, col_center, col_right = st.columns([1, 2, 1])
    with col_center:
        st.title("🎤 Dijital Konuşma Sınavı")
        st.markdown("---")
        
        c1, c2 = st.columns(2)
        with c1: ad = st.text_input("Öğrenci Adı Soyadı")
        with c2: no = st.text_input("Sınıf / Numara")
        
        konular = konulari_getir()
        secilen_konu = st.selectbox("Konu Seçiniz:", list(konular.keys()), index=None)
        
        if secilen_konu:
            detay = konular[secilen_konu]
            k1,k2,k3 = st.columns(3)
            k1.info(f"**Giriş:**\n{detay['Giriş']}")
            k2.warning(f"**Gelişme:**\n{detay['Gelişme']}")
            k3.success(f"**Sonuç:**\n{detay['Sonuç']}")

        st.markdown("<br>", unsafe_allow_html=True)
        ses = st.audio_input("Kayda Başla")
        
        if ses and secilen_konu and st.button("Sınavı Bitir", type="primary"):
            if not ad: st.warning("İsim giriniz.")
            else:
                with st.status("İşleniyor...") as status:
                    ses_data = ses.getvalue()
                    yol = sesi_kalici_kaydet(ses_data, ad)
                    sonuc = sesi_analiz_et(ses_data, secilen_konu, konular[secilen_konu], status)
                    sonuc_kaydet(ad, no, secilen_konu, sonuc.get("transkript"), sonuc.get("yuzluk_sistem_puani"), sonuc, yol)
                    status.update(label="Tamamlandı", state="complete")
                    st.balloons()
                    
                    st.success(f"PUAN: {sonuc.get('yuzluk_sistem_puani')}")
                    with st.expander("Detaylar", expanded=True):
                        st.write(sonuc.get("ogretmen_yorumu"))
                        st.audio(yol)

# --- ADMİN PANELİ EKRANI ---
elif st.session_state['admin_logged_in'] and secim == "📂 Sonuç Arşivi (Admin)":
    st.title("📂 Yönetici Paneli - Tüm Sonuçlar")
    st.markdown("Öğrenci seçerek detayları, metni ve ses kaydını inceleyebilirsiniz.")
    
    df = tum_sonuclari_getir()
    
    if not df.empty:
        # Tablo Görünümü
        st.markdown("### 📋 Öğrenci Listesi")
        
        # Seçim yapılabilen interaktif tablo
        event = st.dataframe(
            df[["id", "ad_soyad", "sinif_no", "konu", "puan_100luk", "tarih"]],
            selection_mode="single-row",
            on_select="rerun",
            use_container_width=True,
            hide_index=True
        )
        
        # Eğer bir satır seçildiyse detayları göster
        if len(event.selection.rows) > 0:
            secilen_index = event.selection.rows[0]
            secilen_kayit = df.iloc[secilen_index]
            
            st.divider()
            st.subheader(f"🔍 İnceleme: {secilen_kayit['ad_soyad']}")
            
            col_admin_1, col_admin_2 = st.columns([1, 1])
            
            # SOL KOLON: Metin ve Ses
            with col_admin_1:
                st.markdown("#### 🗣️ Konuşma Kaydı")
                if os.path.exists(secilen_kayit['ses_yolu']):
                    st.audio(secilen_kayit['ses_yolu'])
                else:
                    st.error(f"Ses dosyası bulunamadı: {secilen_kayit['ses_yolu']}")
                
                st.markdown("#### 📝 Transkript (Metin)")
                st.text_area("", secilen_kayit['konusma_metni'], height=300, disabled=True)
            
            # SAĞ KOLON: Puan Detayları ve Yorum
            with col_admin_2:
                st.markdown("#### 📊 Puan Detayları")
                
                # JSON verisini parse etme
                try:
                    detay_json = json.loads(secilen_kayit['detaylar'])
                    puanlar = detay_json.get("kriter_puanlari", {})
                    yorum = detay_json.get("ogretmen_yorumu", "")
                    
                    # Büyük Puan Göstergesi
                    st.markdown(f"""
                    <div style="background-color:#dcfce7; padding:10px; border-radius:10px; text-align:center; border:2px solid #22c55e;">
                        <h1 style="color:#15803d; margin:0;">{secilen_kayit['puan_100luk']}</h1>
                        <small>Toplam Puan</small>
                    </div>
                    <br>
                    """, unsafe_allow_html=True)
                    
                    # Kriter Tablosu
                    df_puan = pd.DataFrame({
                        "Kriter": ["İçerik", "Düzen", "Dil", "Akıcılık"],
                        "Puan": [puanlar.get("konu_icerik"), puanlar.get("duzen"), puanlar.get("dil"), puanlar.get("akicilik")]
                    })
                    st.table(df_puan.set_index("Kriter"))
                    
                    st.info(f"**Öğretmen Yorumu:**\n{yorum}")
                    
                except Exception as e:
                    st.error(f"Detay verisi bozuk: {e}")
                    
    else:
        st.info("Henüz veritabanında kayıtlı sınav sonucu yok.")
