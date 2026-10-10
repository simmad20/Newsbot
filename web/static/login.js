const texte = {
  passwort: "Falsches Passwort. Bitte nochmal versuchen.",
  gesperrt: "Zu viele Fehlversuche. Anmelden ist in 15 Minuten wieder möglich.",
};
const grund = new URLSearchParams(location.search).get("fehler");
if (grund && texte[grund]) {
  const el = document.getElementById("fehler");
  el.textContent = texte[grund];
  el.hidden = false;
}
