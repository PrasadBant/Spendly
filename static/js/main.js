// main.js — students will add JavaScript here as features are built

document.addEventListener("DOMContentLoaded", function () {
    var deleteForm = document.getElementById("delete-account-form");
    if (deleteForm) {
        deleteForm.addEventListener("submit", function (e) {
            var confirmed = confirm(
                "Are you sure you want to delete your account? This cannot be undone."
            );
            if (!confirmed) {
                e.preventDefault();
            }
        });
    }

    document.querySelectorAll(".expense-delete-form").forEach(function (form) {
        form.addEventListener("submit", function (e) {
            var confirmed = confirm(
                "Are you sure you want to delete this expense? This cannot be undone."
            );
            if (!confirmed) {
                e.preventDefault();
            }
        });
    });
});
