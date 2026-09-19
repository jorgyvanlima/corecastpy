/* CoreCast UI: tema claro/escuro, contadores, revelar ao rolar e fabrica de graficos ApexCharts. */
(function () {
    const raiz = document.documentElement;

    const CC = (window.CC = {
        paleta: {
            indigo: '#6366f1', violeta: '#8b5cf6', ciano: '#06b6d4', esmeralda: '#10b981',
            ambar: '#f59e0b', rosa: '#f43f5e', azul: '#38bdf8', laranja: '#fb923c',
        },
        registros: [],

        escuro() { return raiz.getAttribute('data-bs-theme') === 'dark'; },

        cores() {
            return this.escuro()
                ? { texto: '#b6c2d9', grade: 'rgba(255,255,255,.07)', trilho: 'rgba(255,255,255,.08)', rotulo: '#e5ecf8' }
                : { texto: '#5b6577', grade: 'rgba(15,23,42,.08)', trilho: 'rgba(15,23,42,.08)', rotulo: '#1e293b' };
        },

        mesclar(alvo, origem) {
            for (const k in origem) {
                const v = origem[k];
                alvo[k] = v && typeof v === 'object' && !Array.isArray(v) && alvo[k] && typeof alvo[k] === 'object'
                    ? this.mesclar({ ...alvo[k] }, v) : v;
            }
            return alvo;
        },

        /* Opcoes-base compartilhadas por todos os graficos. */
        base(extra) {
            const c = this.cores();
            return this.mesclar({
                chart: {
                    fontFamily: 'inherit', foreColor: c.texto, background: 'transparent',
                    toolbar: { show: false }, parentHeightOffset: 0,
                    animations: { enabled: true, easing: 'easeinout', speed: 900,
                                  animateGradually: { enabled: true, delay: 120 },
                                  dynamicAnimation: { enabled: true, speed: 450 } },
                },
                grid: { borderColor: c.grade, strokeDashArray: 4 },
                tooltip: { theme: this.escuro() ? 'dark' : 'light' },
                legend: { labels: { colors: c.texto }, markers: { radius: 12 } },
                stroke: { show: true },
                states: { hover: { filter: { type: 'lighten', value: 0.06 } } },
                noData: { text: 'Sem dados' },
            }, extra || {});
        },

        /* Preenchimento em gradiente vertical: cor -> versao mais escura. */
        gradiente(de, para, horizontal) {
            return {
                type: 'gradient',
                gradient: { shade: 'dark', type: horizontal ? 'horizontal' : 'vertical', shadeIntensity: 0.35,
                            gradientToColors: para, inverseColors: false, opacityFrom: 1, opacityTo: 0.85,
                            stops: [0, 100] },
            };
        },

        /* Registra um grafico; ele so e desenhado quando entra na tela (a animacao aparece). */
        grafico(seletor, fabrica) {
            const alvo = document.querySelector(seletor);
            if (!alvo) return;
            const reg = { alvo, fabrica, inst: null };
            this.registros.push(reg);
            observador.observe(alvo);
            alvo._cc = reg;
        },

        desenhar(reg) {
            if (reg.inst) reg.inst.destroy();
            reg.inst = new ApexCharts(reg.alvo, reg.fabrica(this));
            reg.inst.render();
        },
    });

    /* ---------- Revelar ao rolar / desenhar graficos / contadores ---------- */
    function contar(el) {
        const alvo = parseFloat(el.dataset.count) || 0;
        const casas = parseInt(el.dataset.decimals || '0', 10);
        const inicio = performance.now(), duracao = 1600;
        const fmt = v => v.toLocaleString('pt-BR', { minimumFractionDigits: casas, maximumFractionDigits: casas });
        (function passo(agora) {
            const p = Math.min((agora - inicio) / duracao, 1);
            el.textContent = fmt(alvo * (p >= 1 ? 1 : 1 - Math.pow(2, -10 * p)));
            if (p < 1) requestAnimationFrame(passo); else el.textContent = fmt(alvo);
        })(inicio);
    }

    const observador = new IntersectionObserver(entradas => {
        entradas.forEach(e => {
            if (!e.isIntersecting) return;
            const el = e.target;
            observador.unobserve(el);
            if (el._cc) CC.desenhar(el._cc);
            if (el.classList.contains('reveal')) el.classList.add('in');
            if (el.dataset.count !== undefined) contar(el);
        });
    }, { threshold: 0.15 });

    document.addEventListener('DOMContentLoaded', () => {
        document.querySelectorAll('.reveal, [data-count]').forEach(el => observador.observe(el));
    });

    /* ---------- Tema claro/escuro ---------- */
    document.addEventListener('DOMContentLoaded', () => {
        const btn = document.getElementById('btnTema');
        const icone = btn && btn.querySelector('i');
        const atualizar = () => { if (icone) icone.className = 'bi ' + (CC.escuro() ? 'bi-sun-fill' : 'bi-moon-stars-fill'); };
        atualizar();
        if (!btn) return;
        btn.addEventListener('click', e => {
            e.preventDefault();
            const novo = CC.escuro() ? 'light' : 'dark';
            raiz.setAttribute('data-bs-theme', novo);
            try { localStorage.setItem('cc-tema', novo); } catch (_) {}
            atualizar();
            CC.registros.filter(r => r.inst).forEach(r => CC.desenhar(r));
        });
        const tela = document.getElementById('btnTelaCheia');
        if (tela) tela.addEventListener('click', e => {
            e.preventDefault();
            document.fullscreenElement ? document.exitFullscreen() : document.documentElement.requestFullscreen();
        });
    });
})();
