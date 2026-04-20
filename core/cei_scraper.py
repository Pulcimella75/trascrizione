import requests
from bs4 import BeautifulSoup
import re

def fetch_cei_text(reference: str) -> str:
    """
    Recupera il testo della Scrittura dalla versione C.E.I. su laparola.net.
    Rimuove i numeri dei versetti al pedice per rendere il testo leggibile.
    
    :param reference: Il riferimento biblico (es. "Mt 5, 1-12")
    :return: Il brano formattato in formato testo.
    """
    url = "https://www.laparola.net/testo.php"
    
    # Rimuovi spazi e formatta la query per l'URL in modo pulito
    clean_ref = reference.strip()
    
    params = {
        "r": clean_ref,
        "versioni[]": "C.E.I."
    }
    
    try:
        # Usa il timeout per evitare blocchi prolungati
        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()
        
        # Parsea l'HTML con BeautifulSoup
        # Usa il charset corretto visto che potrebbero esserci caratteri accentati (iso-8859-1 o utf-8)
        response.encoding = 'iso-8859-1' 
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # Tutto il testo della bibbia si trova spesso dentro <span> con classe "versetto" 
        # o all'interno della struttura principale. 
        # cerchiamo span class='versetto' e rimuoviamo i "sup" (numeri dei versetti)
        
        # Cerchiamo tutti i blocchi versetto
        versetti = soup.find_all('span', class_='versetto')
        
        if not versetti:
            # Alternativa se la struttura è diversa: prendiamo il testo della pagina
            # e cerchiamo di pulirlo un po'
            # (Ma laparola di solito usa la classe versetto)
            # Cerchiamo il brano dentro il div appropriato
            # un'euristica grezza: cerchiamo "La Sacra Bibbia" nel titolo
            pass  # continuiamo giù per una caduta se non trova 'versetto'
        
        testo_completo = ""
        for v in versetti:
            # Rimuoviamo i tag <sup> che contengono il numero del versetto
            for sup in v.find_all('sup'):
                sup.decompose()
            
            testo_completo += v.get_text().strip() + " "
            
        testo_pulito = testo_completo.strip()
        
        if not testo_pulito:
            return "Nessun testo trovato per questo brano. Controlla la formattazione (es: 'Mt 5, 1-12')."
            
        return testo_pulito
        
    except requests.exceptions.RequestException as e:
        return f"Errore di rete durante il recupero: {e}"
    except Exception as e:
        return f"Errore imprevisto durante l'estrazione: {e}"
