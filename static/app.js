/* Lokal-Radar – Frontend-Logik (kein Framework, kein Build)
 *
 * Die Seite funktioniert auch ohne JavaScript (serverseitig gerendert).
 * Mit JavaScript kommen dazu:
 *   – Aktualisieren ohne Neuladen (das API-Fragment ist dasselbe Markup)
 *   – Umschalten zwischen „Nach Ort" und „Nach Thema"
 *   – „neu"-Marker für alles, was seit dem letzten Besuch erschienen ist
 *   – automatische Auffrischung alle 5 Minuten
 */
(function () {
  'use strict';

  var ergebnisse = document.getElementById('ergebnisse');
  var ladung = document.getElementById('ladung');
  var btnAktualisieren = document.getElementById('aktualisieren');
  var suchfeld = document.getElementById('ort');
  var formular = document.getElementById('suchformular');
  var stand = document.getElementById('stand');

  var SPEICHER_GESEHEN = 'lokalradar.zuletztGesehen';
  var AUTO_MS = 5 * 60 * 1000;
  var letzterAbruf = 0;

  /* ------------------------------------------------------- Hilfsfunktionen */
  function themen() {
    var liste = document.querySelectorAll('input[name="themen"]:checked');
    var out = [];
    for (var i = 0; i < liste.length; i++) { out.push(liste[i].value); }
    return out;
  }

  function parameter(zwingendNeu) {
    var p = new URLSearchParams();
    p.set('ort', (suchfeld.value || '').trim() || 'Köln');
    var t = themen();
    if (t.length) { p.set('themen', t.join(',')); }
    p.set('fmt', 'html');
    if (zwingendNeu) { p.set('refresh', '1'); }
    // Demo-Modus (gespeicherte Feeds) bleibt beim Aktualisieren erhalten
    if (new URLSearchParams(location.search).get('demo') === '1') { p.set('demo', '1'); }
    return p;
  }

  function adresseAnpassen() {
    var p = parameter(false);
    p.delete('fmt');
    p.delete('refresh');
    var neu = location.pathname + '?' + p.toString();
    if (history.replaceState) { history.replaceState(null, '', neu); }
  }

  function ladezustand(an) {
    document.body.classList.toggle('laedt', an);
    if (ladung) { ladung.hidden = !an; }
    if (btnAktualisieren) { btnAktualisieren.disabled = an; }
  }

  /* ------------------------------------------ „neu"-Marker (localStorage) */
  function neuMarkieren() {
    var gesehen = null;
    try { gesehen = parseInt(localStorage.getItem(SPEICHER_GESEHEN) || '0', 10); }
    catch (e) { gesehen = 0; }
    var jetzt = Date.now();
    if (!gesehen) { gesehen = jetzt; }          // erster Besuch: nichts markieren

    var karten = ergebnisse.querySelectorAll('.karte');
    var zaehler = 0;
    for (var i = 0; i < karten.length; i++) {
      var iso = karten[i].getAttribute('data-zeit');
      if (!iso) { continue; }
      var zeit = Date.parse(iso);
      if (zeit && zeit > gesehen) {
        karten[i].classList.add('neu');
        zaehler++;
      }
    }
    try { localStorage.setItem(SPEICHER_GESEHEN, String(jetzt)); } catch (e) { /* egal */ }
    if (zaehler > 0 && ladung) {
      ladung.textContent = zaehler + (zaehler === 1 ? ' neue Meldung' : ' neue Meldungen') +
                           ' seit dem letzten Besuch';
      ladung.hidden = false;
      setTimeout(function () { ladung.hidden = true; }, 4000);
    }
  }

  /* ------------------------------------------------------- Ansicht schalten */
  function ansichtWaehlen(name) {
    var veedel = document.getElementById('ansicht-veedel');
    var themenView = document.getElementById('ansicht-themen');
    if (!veedel || !themenView) { return; }
    veedel.hidden = (name !== 'veedel');
    themenView.hidden = (name !== 'themen');

    var schalter = document.querySelectorAll('.schalter[data-ansicht]');
    for (var i = 0; i < schalter.length; i++) {
      schalter[i].classList.toggle('aktiv', schalter[i].getAttribute('data-ansicht') === name);
    }
    try { sessionStorage.setItem('lokalradar.ansicht', name); } catch (e) { /* egal */ }
  }

  function ansichtWiederherstellen() {
    var gespeichert = null;
    try { gespeichert = sessionStorage.getItem('lokalradar.ansicht'); } catch (e) { /* egal */ }
    ansichtWaehlen(gespeichert === 'themen' ? 'themen' : 'veedel');
  }

  /* ------------------------------------------------------------- Abrufen */
  function holen(zwingendNeu) {
    var jetzt = Date.now();
    if (!zwingendNeu && jetzt - letzterAbruf < 20000) { return Promise.resolve(); }
    letzterAbruf = jetzt;

    ladezustand(true);
    return fetch('/api/news?' + parameter(zwingendNeu).toString(), {
      headers: { 'Accept': 'application/json' },
      cache: 'no-store'
    })
      .then(function (r) {
        if (!r.ok) { throw new Error('HTTP ' + r.status); }
        return r.json();
      })
      .then(function (daten) {
        if (daten && daten.html) {
          ergebnisse.innerHTML = daten.html;
          ansichtWiederherstellen();
          neuMarkieren();
          adresseAnpassen();
          if (stand && daten.generated_at) {
            var d = new Date(daten.generated_at);
            stand.textContent = 'Stand: ' + d.toLocaleString('de-DE');
          }
          if (daten.warnungen && daten.warnungen.length) {
            console.warn('Lokal-Radar Hinweise:', daten.warnungen);
          }
        }
      })
      .catch(function (fehler) {
        if (ladung) {
          ladung.textContent = 'Aktualisierung fehlgeschlagen: ' + fehler.message +
                               ' – die angezeigten Meldungen bleiben stehen.';
          ladung.hidden = false;
          setTimeout(function () { ladung.hidden = true; }, 6000);
        }
      })
      .finally(function () { ladezustand(false); });
  }

  /* ------------------------------------------------------------ Ereignisse */
  if (formular) {
    formular.addEventListener('submit', function (ev) {
      ev.preventDefault();
      holen(true);
    });
  }

  if (btnAktualisieren) {
    btnAktualisieren.addEventListener('click', function () { holen(true); });
  }

  // Themen-Checkboxen und Orts-Chips
  document.addEventListener('change', function (ev) {
    if (ev.target && ev.target.name === 'themen') { holen(false); }
  });

  document.addEventListener('click', function (ev) {
    var chip = ev.target.closest ? ev.target.closest('.ort-chip, .chip[data-ort]') : null;
    if (chip && chip.getAttribute('data-ort')) {
      suchfeld.value = chip.getAttribute('data-ort');
      holen(true);
      return;
    }

    var schalter = ev.target.closest ? ev.target.closest('.schalter[data-ansicht]') : null;
    if (schalter) {
      ansichtWaehlen(schalter.getAttribute('data-ansicht'));
      return;
    }

    var thema = ev.target.closest ? ev.target.closest('.themen-chip[data-kategorie]') : null;
    if (thema) {
      ansichtWaehlen('themen');
      var ziel = document.getElementById('thema-' + thema.getAttribute('data-kategorie'));
      if (ziel && ziel.scrollIntoView) {
        ziel.scrollIntoView({ behavior: 'smooth', block: 'start' });
      }
    }
  });

  // Tastatur: „r" lädt neu
  document.addEventListener('keydown', function (ev) {
    if (ev.key === 'r' && !ev.metaKey && !ev.ctrlKey &&
        document.activeElement !== suchfeld) {
      ev.preventDefault();
      holen(true);
    }
  });

  // Automatisch auffrischen, aber nur wenn das Tab sichtbar ist
  setInterval(function () {
    if (!document.hidden) { holen(false); }
  }, AUTO_MS);

  ansichtWiederherstellen();
  neuMarkieren();
})();
