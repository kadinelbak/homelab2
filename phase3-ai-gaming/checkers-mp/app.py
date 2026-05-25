from __future__ import annotations

from dataclasses import dataclass
from threading import Lock
from typing import Dict, List, Optional, Tuple
from uuid import uuid4

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field


Board = List[List[str]]
Position = Tuple[int, int]


@dataclass
class Game:
    game_id: str
    board: Board
    red_player_id: str
    black_player_id: Optional[str]
    red_player_name: str
    black_player_name: Optional[str]
    turn: str
    status: str
    winner: Optional[str]
    must_continue_from: Optional[Position]


class CreateGameRequest(BaseModel):
    player_name: str = Field(min_length=1, max_length=40)


class JoinGameRequest(BaseModel):
    player_name: str = Field(min_length=1, max_length=40)


class MoveRequest(BaseModel):
    player_id: str
    from_row: int
    from_col: int
    to_row: int
    to_col: int


class GameResponse(BaseModel):
    game_id: str
    board: Board
    turn: str
    status: str
    winner: Optional[str]
    your_color: Optional[str]
    players: Dict[str, Optional[str]]
    must_continue_from: Optional[Tuple[int, int]]


class GameSummary(BaseModel):
    game_id: str
    status: str
    turn: str
    players: Dict[str, Optional[str]]


app = FastAPI(title="Game Server API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

_games: Dict[str, Game] = {}
_lock = Lock()


def initial_board() -> Board:
    board = [["." for _ in range(8)] for _ in range(8)]
    for r in range(3):
        for c in range(8):
            if (r + c) % 2 == 1:
                board[r][c] = "b"
    for r in range(5, 8):
        for c in range(8):
            if (r + c) % 2 == 1:
                board[r][c] = "r"
    return board


def inside(r: int, c: int) -> bool:
    return 0 <= r < 8 and 0 <= c < 8


def piece_color(piece: str) -> Optional[str]:
    if piece in ("r", "R"):
        return "red"
    if piece in ("b", "B"):
        return "black"
    return None


def is_king(piece: str) -> bool:
    return piece in ("R", "B")


def directions_for_piece(piece: str) -> List[Tuple[int, int]]:
    if piece == "r":
        return [(-1, -1), (-1, 1)]
    if piece == "b":
        return [(1, -1), (1, 1)]
    return [(-1, -1), (-1, 1), (1, -1), (1, 1)]


def move_dirs(piece: str) -> List[Tuple[int, int]]:
    return directions_for_piece(piece)


def capture_moves(board: Board, row: int, col: int) -> List[Position]:
    piece = board[row][col]
    if piece == ".":
        return []
    color = piece_color(piece)
    options: List[Position] = []
    for dr, dc in directions_for_piece(piece):
        mr, mc = row + dr, col + dc
        tr, tc = row + 2 * dr, col + 2 * dc
        if not inside(mr, mc) or not inside(tr, tc):
            continue
        middle = board[mr][mc]
        target = board[tr][tc]
        if target != ".":
            continue
        if middle != "." and piece_color(middle) != color:
            options.append((tr, tc))
    return options


def normal_moves(board: Board, row: int, col: int) -> List[Position]:
    piece = board[row][col]
    if piece == ".":
        return []
    options: List[Position] = []
    for dr, dc in move_dirs(piece):
        tr, tc = row + dr, col + dc
        if inside(tr, tc) and board[tr][tc] == ".":
            options.append((tr, tc))
    return options


def all_capture_sources(board: Board, color: str) -> List[Position]:
    out: List[Position] = []
    for r in range(8):
        for c in range(8):
            piece = board[r][c]
            if piece != "." and piece_color(piece) == color and capture_moves(board, r, c):
                out.append((r, c))
    return out


def has_any_legal_move(board: Board, color: str) -> bool:
    must_capture = all_capture_sources(board, color)
    if must_capture:
        return True
    for r in range(8):
        for c in range(8):
            piece = board[r][c]
            if piece != "." and piece_color(piece) == color and normal_moves(board, r, c):
                return True
    return False


def promote_if_needed(piece: str, row: int) -> str:
    if piece == "r" and row == 0:
        return "R"
    if piece == "b" and row == 7:
        return "B"
    return piece


def color_for_player(game: Game, player_id: str) -> Optional[str]:
    if player_id == game.red_player_id:
        return "red"
    if game.black_player_id and player_id == game.black_player_id:
        return "black"
    return None


def winner_name(game: Game, color: str) -> str:
    return game.red_player_name if color == "red" else (game.black_player_name or "black")


def to_response(game: Game, player_id: Optional[str] = None) -> GameResponse:
    return GameResponse(
        game_id=game.game_id,
        board=game.board,
        turn=game.turn,
        status=game.status,
        winner=game.winner,
        your_color=color_for_player(game, player_id) if player_id else None,
        players={"red": game.red_player_name, "black": game.black_player_name},
        must_continue_from=game.must_continue_from,
    )


@app.get("/health")
def health() -> Dict[str, object]:
    return {"status": "ok", "service": "game-server", "modules": ["checkers", "hearts"]}


@app.get("/api/modules")
def modules() -> List[Dict[str, str]]:
    return [
        {"id": "checkers", "status": "active", "transport": "rest"},
        {"id": "hearts", "status": "external_service", "transport": "socket.io"},
    ]


@app.get("/api/checkers/games", response_model=List[GameSummary])
@app.get("/api/games", response_model=List[GameSummary])
def list_games() -> List[GameSummary]:
    with _lock:
        return [
            GameSummary(
                game_id=game.game_id,
                status=game.status,
                turn=game.turn,
                players={"red": game.red_player_name, "black": game.black_player_name},
            )
            for game in sorted(_games.values(), key=lambda item: item.game_id, reverse=True)
        ]


@app.post("/api/checkers/games")
@app.post("/api/games")
def create_game(payload: CreateGameRequest) -> Dict[str, str]:
    with _lock:
        game_id = uuid4().hex[:8]
        player_id = uuid4().hex
        game = Game(
            game_id=game_id,
            board=initial_board(),
            red_player_id=player_id,
            black_player_id=None,
            red_player_name=payload.player_name.strip(),
            black_player_name=None,
            turn="red",
            status="waiting_for_player",
            winner=None,
            must_continue_from=None,
        )
        _games[game_id] = game
    return {"game_id": game_id, "player_id": player_id, "color": "red"}


@app.post("/api/checkers/games/{game_id}/join")
@app.post("/api/games/{game_id}/join")
def join_game(game_id: str, payload: JoinGameRequest) -> Dict[str, str]:
    with _lock:
        game = _games.get(game_id)
        if not game:
            raise HTTPException(status_code=404, detail="Game not found")
        if game.black_player_id:
            raise HTTPException(status_code=409, detail="Game is already full")
        player_id = uuid4().hex
        game.black_player_id = player_id
        game.black_player_name = payload.player_name.strip()
        game.status = "active"
    return {"game_id": game_id, "player_id": player_id, "color": "black"}


@app.get("/api/checkers/games/{game_id}", response_model=GameResponse)
@app.get("/api/games/{game_id}", response_model=GameResponse)
def get_game(game_id: str, player_id: Optional[str] = None) -> GameResponse:
    with _lock:
        game = _games.get(game_id)
        if not game:
            raise HTTPException(status_code=404, detail="Game not found")
        return to_response(game, player_id)


@app.post("/api/checkers/games/{game_id}/move", response_model=GameResponse)
@app.post("/api/games/{game_id}/move", response_model=GameResponse)
def move(game_id: str, payload: MoveRequest) -> GameResponse:
    with _lock:
        game = _games.get(game_id)
        if not game:
            raise HTTPException(status_code=404, detail="Game not found")
        if game.status != "active":
            raise HTTPException(status_code=409, detail="Game is not active")

        player_color = color_for_player(game, payload.player_id)
        if player_color is None:
            raise HTTPException(status_code=403, detail="Invalid player")
        if game.turn != player_color:
            raise HTTPException(status_code=409, detail="Not your turn")

        fr, fc = payload.from_row, payload.from_col
        tr, tc = payload.to_row, payload.to_col
        if not (inside(fr, fc) and inside(tr, tc)):
            raise HTTPException(status_code=400, detail="Out of bounds")

        piece = game.board[fr][fc]
        if piece == "." or piece_color(piece) != player_color:
            raise HTTPException(status_code=400, detail="Invalid source piece")
        if game.board[tr][tc] != ".":
            raise HTTPException(status_code=400, detail="Target square is occupied")

        if game.must_continue_from is not None:
            if (fr, fc) != game.must_continue_from:
                raise HTTPException(status_code=409, detail="You must continue capturing with the same piece")

        must_capture_sources = all_capture_sources(game.board, player_color)
        is_capture = abs(tr - fr) == 2 and abs(tc - fc) == 2
        is_normal = abs(tr - fr) == 1 and abs(tc - fc) == 1

        if must_capture_sources and not is_capture:
            raise HTTPException(status_code=409, detail="Capture is mandatory")

        if is_normal:
            if (tr, tc) not in normal_moves(game.board, fr, fc):
                raise HTTPException(status_code=400, detail="Illegal move")
            game.board[tr][tc] = promote_if_needed(piece, tr)
            game.board[fr][fc] = "."
            game.must_continue_from = None
            game.turn = "black" if player_color == "red" else "red"
        elif is_capture:
            if (tr, tc) not in capture_moves(game.board, fr, fc):
                raise HTTPException(status_code=400, detail="Illegal capture")
            mr, mc = (fr + tr) // 2, (fc + tc) // 2
            game.board[tr][tc] = promote_if_needed(piece, tr)
            game.board[fr][fc] = "."
            game.board[mr][mc] = "."

            next_caps = capture_moves(game.board, tr, tc)
            if next_caps:
                game.must_continue_from = (tr, tc)
            else:
                game.must_continue_from = None
                game.turn = "black" if player_color == "red" else "red"
        else:
            raise HTTPException(status_code=400, detail="Move must be one step diagonal or capture jump")

        opponent = "black" if player_color == "red" else "red"
        opponent_has_piece = any(piece_color(p) == opponent for row in game.board for p in row)
        opponent_can_move = has_any_legal_move(game.board, opponent)
        if not opponent_has_piece or not opponent_can_move:
            game.status = "finished"
            game.winner = winner_name(game, player_color)

        return to_response(game, payload.player_id)
