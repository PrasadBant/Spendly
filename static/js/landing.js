(function () {
    var YOUTUBE_VIDEO_ID = 'dQw4w9WgXcQ'; // placeholder — replace with the real video ID

    var trigger = document.getElementById('how-it-works-btn');
    var modal = document.getElementById('video-modal');
    var closeBtn = document.getElementById('video-modal-close');
    var iframe = document.getElementById('video-modal-iframe');

    if (!trigger || !modal || !closeBtn || !iframe) return;

    function openModal(event) {
        event.preventDefault();
        iframe.src = 'https://www.youtube.com/embed/' + YOUTUBE_VIDEO_ID + '?autoplay=1&rel=0';
        modal.classList.add('is-open');
        document.body.style.overflow = 'hidden';
    }

    function closeModal() {
        modal.classList.remove('is-open');
        iframe.src = ''; // clears the embed so the video stops playing
        document.body.style.overflow = '';
    }

    trigger.addEventListener('click', openModal);
    closeBtn.addEventListener('click', closeModal);

    modal.addEventListener('click', function (event) {
        if (event.target === modal) closeModal();
    });

    document.addEventListener('keydown', function (event) {
        if (event.key === 'Escape' && modal.classList.contains('is-open')) closeModal();
    });
})();
