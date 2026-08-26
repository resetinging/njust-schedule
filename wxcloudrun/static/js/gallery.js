/**
 * 校历 & 照片墙 — 横向滚动 + Lightbox 查看
 */
(function () {
    'use strict';

    let images = [];
    let currentIndex = 0;

    // ============================================================
    // 初始化
    // ============================================================

    async function init() {
        try {
            const resp = await fetch('/api/gallery-images');
            const data = await resp.json();
            images = data.images || [];
        } catch (e) {
            images = [];
        }

        const countEl = document.getElementById('gallery-count');
        const scrollEl = document.getElementById('gallery-scroll');
        const emptyEl = document.getElementById('gallery-empty');

        if (images.length === 0) {
            countEl.textContent = '暂无照片';
            scrollEl.style.display = 'none';
            if (emptyEl) emptyEl.style.display = 'flex';
            return;
        }

        countEl.textContent = images.length + ' 张照片';
        if (emptyEl) emptyEl.style.display = 'none';
        scrollEl.style.display = 'flex';

        renderCards(scrollEl);
        bindScrollWheel(scrollEl);
        bindKeyboard();
        bindOverlayClick();
    }

    // ============================================================
    // 渲染卡片
    // ============================================================

    function renderCards(container) {
        container.innerHTML = '';
        images.forEach(function (filename, i) {
            var card = document.createElement('div');
            card.className = 'gallery-card';
            card.title = '点击查看大图';
            card.setAttribute('role', 'button');
            card.tabIndex = 0;
            card.addEventListener('click', function () { openLightbox(i); });
            card.addEventListener('keydown', function (e) {
                if (e.key === 'Enter' || e.key === ' ') {
                    e.preventDefault();
                    openLightbox(i);
                }
            });

            var img = document.createElement('img');
            img.className = 'gallery-card-img';
            img.src = '/static/gallery/' + encodeURI(filename);
            img.alt = filename;
            img.loading = 'lazy';

            var label = document.createElement('div');
            label.className = 'gallery-card-label';
            label.textContent = filename;

            card.appendChild(img);
            card.appendChild(label);
            container.appendChild(card);
        });
    }

    // ============================================================
    // 鼠标滚轮 → 横向滚动
    // ============================================================

    function bindScrollWheel(container) {
        container.addEventListener('wheel', function (e) {
            // 如果用户按住了 shift 或是触控板横向滑动，不拦截
            if (e.deltaX !== 0) return;
            // 将纵向滚轮转为横向
            e.preventDefault();
            container.scrollLeft += e.deltaY;
        }, { passive: false });
    }

    // ============================================================
    // Lightbox
    // ============================================================

    window.openLightbox = function (index) {
        currentIndex = index;
        updateLightbox();
        document.getElementById('lightbox').style.display = 'flex';
        document.body.style.overflow = 'hidden';
    };

    window.closeLightbox = function () {
        document.getElementById('lightbox').style.display = 'none';
        document.body.style.overflow = '';
    };

    window.navigateLightbox = function (delta) {
        currentIndex = (currentIndex + delta + images.length) % images.length;
        updateLightbox();
    };

    function updateLightbox() {
        var filename = images[currentIndex];
        document.getElementById('lightbox-img').src = '/static/gallery/' + encodeURI(filename);
        document.getElementById('lightbox-img').alt = filename;
        document.getElementById('lightbox-counter').textContent =
            (currentIndex + 1) + ' / ' + images.length;
        document.getElementById('lightbox-filename').textContent = filename;
    }

    // ============================================================
    // 键盘事件
    // ============================================================

    function bindKeyboard() {
        document.addEventListener('keydown', function (e) {
            var overlay = document.getElementById('lightbox');
            if (overlay.style.display !== 'flex') return;

            if (e.key === 'Escape') {
                closeLightbox();
            } else if (e.key === 'ArrowLeft') {
                navigateLightbox(-1);
            } else if (e.key === 'ArrowRight') {
                navigateLightbox(1);
            }
        });
    }

    // 点击遮罩背景关闭
    function bindOverlayClick() {
        document.getElementById('lightbox').addEventListener('click', function (e) {
            if (e.target === this) {
                closeLightbox();
            }
        });
    }

    // ============================================================
    // 启动
    // ============================================================

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
