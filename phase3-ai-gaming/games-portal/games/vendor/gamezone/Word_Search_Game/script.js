const WORDS = [
  "BANANA",
  "KIWI",
  "MANGO",
  "ORANGE",
  "APPLE",
  "WATERMELON",
  "GRAPES",
  "PINEAPPLE",
];

const SIZE = 12;
const DIRECTIONS = [
  { row: 0, col: 1 },
  { row: 1, col: 0 },
  { row: 1, col: 1 },
  { row: 1, col: -1 },
];

let grid = [];
let found = new Set();
let selection = [];
let isSelecting = false;

const lettersEl = document.getElementById("letters");
const hintEl = document.getElementById("hint");

function randomLetter() {
  return String.fromCharCode(65 + Math.floor(Math.random() * 26));
}

function emptyGrid() {
  grid = Array.from({ length: SIZE }, () =>
    Array.from({ length: SIZE }, () => ({ letter: "", word: null }))
  );
}

function canPlace(word, row, col, direction) {
  for (let i = 0; i < word.length; i += 1) {
    const r = row + direction.row * i;
    const c = col + direction.col * i;
    if (r < 0 || r >= SIZE || c < 0 || c >= SIZE) return false;
    const existing = grid[r][c].letter;
    if (existing && existing !== word[i]) return false;
  }
  return true;
}

function placeWord(word) {
  for (let attempt = 0; attempt < 120; attempt += 1) {
    const direction = DIRECTIONS[Math.floor(Math.random() * DIRECTIONS.length)];
    const row = Math.floor(Math.random() * SIZE);
    const col = Math.floor(Math.random() * SIZE);
    if (!canPlace(word, row, col, direction)) continue;

    for (let i = 0; i < word.length; i += 1) {
      const cell = grid[row + direction.row * i][col + direction.col * i];
      cell.letter = word[i];
      cell.word = word;
    }
    return true;
  }
  return false;
}

function fillGrid() {
  emptyGrid();
  WORDS.slice()
    .sort((a, b) => b.length - a.length)
    .forEach(placeWord);

  for (const row of grid) {
    for (const cell of row) {
      if (!cell.letter) cell.letter = randomLetter();
    }
  }
}

function renderHints() {
  hintEl.innerHTML = "";
  for (const word of WORDS) {
    const item = document.createElement("p");
    item.textContent = word;
    item.dataset.word = word;
    if (found.has(word)) item.classList.add("done");
    hintEl.appendChild(item);
  }
}

function renderGrid() {
  lettersEl.innerHTML = "";
  grid.forEach((row, rowIndex) => {
    row.forEach((cell, colIndex) => {
      const button = document.createElement("button");
      button.className = "individual";
      button.type = "button";
      button.textContent = cell.letter;
      button.dataset.row = String(rowIndex);
      button.dataset.col = String(colIndex);
      button.setAttribute("aria-label", `Letter ${cell.letter}`);
      lettersEl.appendChild(button);
    });
  });
}

function getCellFromEvent(event) {
  const point = event.touches?.[0] || event.changedTouches?.[0] || event;
  const target = document.elementFromPoint(point.clientX, point.clientY);
  return target?.closest?.(".individual") || null;
}

function cellKey(cell) {
  return `${cell.dataset.row},${cell.dataset.col}`;
}

function clearSelection() {
  selection = [];
  lettersEl.querySelectorAll(".colorPurple").forEach((cell) => {
    cell.classList.remove("colorPurple");
  });
}

function addCell(cell) {
  if (!cell || selection.some((item) => item.key === cellKey(cell))) return;
  cell.classList.add("colorPurple");
  selection.push({
    key: cellKey(cell),
    row: Number(cell.dataset.row),
    col: Number(cell.dataset.col),
    letter: cell.textContent,
    element: cell,
  });
}

function isStraightLine(items) {
  if (items.length < 2) return false;
  const rowStep = Math.sign(items[1].row - items[0].row);
  const colStep = Math.sign(items[1].col - items[0].col);
  if (rowStep === 0 && colStep === 0) return false;

  for (let i = 1; i < items.length; i += 1) {
    const prev = items[i - 1];
    const current = items[i];
    if (current.row - prev.row !== rowStep || current.col - prev.col !== colStep) {
      return false;
    }
  }
  return true;
}

function finishSelection() {
  const selectedWord = selection.map((item) => item.letter).join("");
  const reversedWord = selection
    .map((item) => item.letter)
    .reverse()
    .join("");
  const match = WORDS.find((word) => word === selectedWord || word === reversedWord);

  if (match && isStraightLine(selection)) {
    found.add(match);
    selection.forEach((item) => item.element.classList.add("correctlySelected"));
    renderHints();
    if (found.size === WORDS.length) {
      hintEl.innerHTML = '<p id="message">GOOD JOB!</p>';
    }
  }
  clearSelection();
}

function startSelection(event) {
  event.preventDefault();
  clearSelection();
  isSelecting = true;
  addCell(getCellFromEvent(event));
}

function moveSelection(event) {
  if (!isSelecting) return;
  event.preventDefault();
  addCell(getCellFromEvent(event));
}

function endSelection(event) {
  if (!isSelecting) return;
  event.preventDefault();
  isSelecting = false;
  finishSelection();
}

function bindEvents() {
  lettersEl.addEventListener("pointerdown", startSelection);
  lettersEl.addEventListener("pointermove", moveSelection);
  window.addEventListener("pointerup", endSelection);
  lettersEl.addEventListener("touchstart", startSelection, { passive: false });
  lettersEl.addEventListener("touchmove", moveSelection, { passive: false });
  window.addEventListener("touchend", endSelection, { passive: false });
}

function startGame() {
  fillGrid();
  renderHints();
  renderGrid();
  bindEvents();
}

startGame();
