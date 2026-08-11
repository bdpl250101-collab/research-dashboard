/* 주간 연구 대시보드 — 테마 토글 + 검색 필터 (의존성 없음) */

(function () {
  "use strict";

  // ── 테마 ────────────────────────────────────────────────────────
  // 저장된 선택이 있으면 그것을, 없으면 OS 설정을 따른다(속성 없음 = OS 위임).
  var root = document.documentElement;
  var STORAGE_KEY = "dashboard-theme";

  function currentTheme() {
    var stamped = root.getAttribute("data-theme");
    if (stamped) return stamped;
    return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
  }

  function updateLabel(theme) {
    var button = document.querySelector(".theme-toggle");
    if (!button) return;
    button.textContent = theme === "dark" ? "라이트 모드" : "다크 모드";
    button.setAttribute("aria-label", theme === "dark" ? "라이트 모드로 전환" : "다크 모드로 전환");
  }

  function applyTheme(theme) {
    root.setAttribute("data-theme", theme);
    updateLabel(theme);
  }

  var media = window.matchMedia("(prefers-color-scheme: dark)");

  try {
    var saved = localStorage.getItem(STORAGE_KEY);
    if (saved === "dark" || saved === "light") applyTheme(saved);
  } catch (e) { /* 프라이빗 모드 등에서 localStorage 차단 */ }

  document.addEventListener("click", function (event) {
    if (!event.target.closest(".theme-toggle")) return;
    var next = currentTheme() === "dark" ? "light" : "dark";
    applyTheme(next);
    try { localStorage.setItem(STORAGE_KEY, next); } catch (e) { /* 무시 */ }
  });

  // 저장된 선택이 없으면 data-theme 를 찍지 않는다. 찍어 버리면 그 시점의 OS
  // 설정으로 굳어져, 이후 OS 테마가 바뀌어도 페이지가 따라가지 않는다.
  updateLabel(currentTheme());
  media.addEventListener("change", function () {
    if (!root.getAttribute("data-theme")) updateLabel(currentTheme());
  });

  // ── 검색 ────────────────────────────────────────────────────────
  var input = document.querySelector("#search");
  if (!input) return;

  var items = Array.prototype.slice.call(document.querySelectorAll(".items > li"));
  var sections = Array.prototype.slice.call(document.querySelectorAll(".topic-card"));
  var noResults = document.querySelector(".no-results");

  // 검색 대상 문자열을 미리 만들어 둔다 (입력마다 DOM 을 다시 읽지 않도록)
  items.forEach(function (li) {
    li.dataset.haystack = (li.textContent || "").toLowerCase();
  });

  function applyFilter(query) {
    var q = query.trim().toLowerCase();
    var anyVisible = false;

    items.forEach(function (li) {
      var hit = !q || li.dataset.haystack.indexOf(q) !== -1;
      li.hidden = !hit;
      if (hit) anyVisible = true;
    });

    // 항목이 모두 숨겨진 섹션은 섹션째 감춘다
    sections.forEach(function (section) {
      var visible = section.querySelectorAll(".items > li:not([hidden])").length;
      var hasItems = section.querySelectorAll(".items > li").length > 0;
      section.hidden = q ? visible === 0 : false;
      var counter = section.querySelector("h3 .count");
      if (counter && hasItems) {
        counter.textContent = q ? visible + "건 (검색)" : counter.dataset.total;
      }
    });

    if (noResults) noResults.style.display = q && !anyVisible ? "block" : "none";
  }

  // 필터 해제 시 원래 건수로 되돌리기 위해 초기값을 보관
  document.querySelectorAll("h3 .count").forEach(function (counter) {
    counter.dataset.total = counter.textContent;
  });

  var timer = null;
  input.addEventListener("input", function () {
    clearTimeout(timer);
    timer = setTimeout(function () { applyFilter(input.value); }, 120);
  });

  input.addEventListener("keydown", function (event) {
    if (event.key === "Escape") {
      input.value = "";
      applyFilter("");
    }
  });
})();
