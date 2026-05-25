document.addEventListener('DOMContentLoaded', () => {
    let translations = {};
    const langSelector = document.getElementById('lang-selector');

    fetch('/static/js/i18n.json')
        .then(response => response.json())
        .then(data => {
            translations = data;
            const savedLang = localStorage.getItem('lang') || 'en';
            applyLanguage(savedLang);
            if (langSelector) langSelector.value = savedLang;
        });

    function applyLanguage(lang) {
        document.querySelectorAll('[data-i18n]').forEach(el => {
            const key = el.getAttribute('data-i18n');
            if (translations[lang] && translations[lang][key]) {
                el.innerText = translations[lang][key];
            }
        });
        localStorage.setItem('lang', lang);
    }

    if (langSelector) {
        langSelector.addEventListener('change', (e) => {
            applyLanguage(e.target.value);
        });
    }
});
