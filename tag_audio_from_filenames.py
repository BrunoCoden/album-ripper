#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import sys
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from pathlib import Path
from typing import Iterable

COMMON_ONE_WORD_ARTISTS = {
    'AURORA',
    'Aurora',
    'Bush',
    'Creed',
    'Disturbed',
    'Incubus',
    'Kodaline',
    'Muse',
    'NF',
    'Paramore',
    'Seafret',
    'Slipknot',
    'Staind',
}

COMMON_TWO_WORD_ARTISTS = {
    'Bill Withers',
    'Black Pumas',
    'Childish Gambino',
    'Chris Cornell',
    'Collective Soul',
    'Ed Sheeran',
    'Jack Harlow',
    'Johnny Cash',
    'Limp Bizkit',
    'Linkin Park',
    'Mad Season',
    'Michael Kiwanuka',
    'Mike Shinoda',
    'Pearl Jam',
    'Radical Face',
    'Stone Sour',
    'The xx',
    'Fuel',
}

COMMON_THREE_WORD_ARTISTS = {
    '3 Doors Down',
    'Alice In Chains',
    'Coheed and Cambria',
    'Guns N Roses',
    'Puddle Of Mudd',
    'Red Hot Chili',
    'Stone Temple Pilots',
    'The Black Crowes',
}

KNOWN_ARTISTS = COMMON_ONE_WORD_ARTISTS | COMMON_TWO_WORD_ARTISTS | COMMON_THREE_WORD_ARTISTS

from mutagen import File as MutagenFile
from mutagen.easyid3 import EasyID3
from mutagen.id3 import ID3NoHeaderError
from mutagen.mp3 import MP3

AUDIO_EXTENSIONS = {'.mp3', '.m4a', '.mp4', '.flac', '.ogg', '.opus'}
NOISE_SUFFIX_PATTERNS = [
    r'First Official Performance',
    r'Official HD Music Video',
    r'Official Music Video',
    r'Official Video HD',
    r'Official HD Video',
    r'Official Video',
    r'Official Audio',
    r'Official Performance',
    r'Official Live Session',
    r'Official Lyric Video',
    r'Lyric Video',
    r'HD UPGRADE',
    r'HD Upgrade',
    r'HD Video',
    r'VIDEO HD',
    r'Official',
]
PLAYLIST_ID_RE = re.compile(r'^(PL|RD|OLAK|UC|UU|FL|LL)[A-Za-z0-9_-]{8,}$')
TRACK_PREFIX_RE = re.compile(r'^(?P<track>\d{1,3})(?:\s*[-_.]\s*|__+)(?P<rest>.+)$')
SEPARATOR_CANDIDATES = ['_-_', ' - ', ' – ']
MULTISPACE_RE = re.compile(r'\s+')
DANGLING_SEP_RE = re.compile(r'(?:\s+-\s+|\s*[_-]\s*)+$')
RAW_YOUTUBE_ID_SUFFIX_RE = re.compile(r'(?:\s*[-–]\s*|__?)(?P<id>[A-Za-z0-9_-]{11})$')
YOUTUBE_ID_SUFFIX_RE = re.compile(r'(?:\s*[-_–]\s*)(?P<id>[A-Za-z0-9_-]{11})$')
NOISE_BRACKET_RE = re.compile(r'(?P<open>[\[(])\s*(?:official|video|audio|hd|4k|lyrics?|lyric video)[^\])]*[\])]', re.IGNORECASE)
MUSICBRAINZ_API_URL = 'https://musicbrainz.org/ws/2/recording'
MUSICBRAINZ_USER_AGENT = 'tag-audio-from-filenames/1.0 (local helper)'
YOUTUBE_OEMBED_URL = 'https://www.youtube.com/oembed'
YOUTUBE_ID_RE = re.compile(r'(?P<id>[A-Za-z0-9_-]{11})$')
TRAILING_YOUTUBE_ID_RE = re.compile(r'(?:__|\s[-_–]\s|[-_–])(?P<id>[A-Za-z0-9_-]{11})$')
YOUTUBE_ID_ARTIST_OVERRIDES = {
    'Xpl2LwFt8x8': 'Creed',
    'DRlptgSj9qM': 'The Goo Goo Dolls',
    'O4bwvdoTV-U': 'Korn',
}




def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description='Recorre una carpeta de audio, infiere tags desde el nombre del archivo y los escribe en metadata compatible.'
    )
    parser.add_argument('folder', help='Carpeta raíz a recorrer')
    parser.add_argument('--dry-run', action='store_true', help='Muestra qué cambiaría sin escribir metadata')
    parser.add_argument('--rename', action='store_true', help='Renombra archivos a "Artist - Title-VIDEO_ID.ext" cuando sea posible')
    parser.add_argument('--force-album-from-parent', action='store_true', help='Usa siempre la carpeta padre como álbum, incluso si parece una playlist ID')
    parser.add_argument('--youtube-assist', action='store_true', help='Para archivos con ID de YouTube, consulta oEmbed y usa el canal/título del video antes de otros métodos')
    parser.add_argument('--musicbrainz-assist', action='store_true', help='Para archivos sin artista, consulta MusicBrainz y permite elegir uno en la terminal')
    parser.add_argument('--musicbrainz-auto-apply', action='store_true', help='Aplica automáticamente la mejor coincidencia de MusicBrainz cuando parece confiable')
    parser.add_argument('--musicbrainz-limit', type=int, default=5, help='Cantidad máxima de candidatos de MusicBrainz a mostrar por archivo sin artista')
    return parser.parse_args()


def iter_audio_files(root: Path) -> Iterable[Path]:
    for path in sorted(root.rglob('*')):
        if path.is_file() and path.suffix.lower() in AUDIO_EXTENSIONS:
            yield path


def normalize_text(raw: str) -> str:
    text = raw.replace('–', '-').replace('—', '-').replace('_', ' ').strip()
    text = text.replace("What s", "What's")
    text = text.replace("What S", "What's")
    text = text.replace(" N ", " N' ")
    text = MULTISPACE_RE.sub(' ', text)
    text = DANGLING_SEP_RE.sub('', text).strip()
    return text


def normalize_artist(raw: str | None) -> str | None:
    if not raw:
        return None
    artist = normalize_text(raw)
    if artist.isupper() and len(artist) <= 4:
        return artist
    if artist.isupper():
        artist = artist.title()
    artist = artist.replace(" N ", " N' ")
    artist = artist.replace(" N' Roses", " N' Roses")
    return artist


def strip_trailing_youtube_id(raw: str) -> str:
    return RAW_YOUTUBE_ID_SUFFIX_RE.sub('', raw).strip()


def clean_title(raw: str) -> str:
    title = strip_trailing_youtube_id(raw)
    title = normalize_text(title)
    title = YOUTUBE_ID_SUFFIX_RE.sub('', title).strip()
    changed = True
    while changed:
        changed = False
        for pattern in NOISE_SUFFIX_PATTERNS:
            cleaned = re.sub(rf'(?:\s+-\s+|\s+)?{pattern}$', '', title, flags=re.IGNORECASE).strip()
            if cleaned != title:
                title = cleaned
                changed = True
        cleaned = NOISE_BRACKET_RE.sub('', title).strip()
        if cleaned != title:
            title = cleaned
            changed = True
    title = title.replace(" Pt ", " Pt. ")
    title = MULTISPACE_RE.sub(' ', title)
    title = DANGLING_SEP_RE.sub('', title).strip()
    return title


def infer_album_from_parent(parent_name: str, force: bool) -> str | None:
    name = normalize_text(parent_name)
    if not name:
        return None
    if force:
        return name
    if PLAYLIST_ID_RE.match(parent_name):
        return None
    return name


def infer_artist_title_without_separator(stem: str) -> tuple[str | None, str]:
    normalized = normalize_text(stem)

    if ' -- ' in normalized:
        _left, right = normalized.rsplit(' -- ', 1)
        if right:
            return None, right

    if '__' in stem:
        left, right = stem.rsplit('__', 1)
        if normalize_text(right).isdigit():
            return None, left

    normalized_words = normalized.split()

    if len(normalized_words) > 1 and normalized_words[0] in COMMON_ONE_WORD_ARTISTS:
        return normalized_words[0], ' '.join(normalized_words[1:])

    for size, candidates in ((3, COMMON_THREE_WORD_ARTISTS), (2, COMMON_TWO_WORD_ARTISTS)):
        if len(normalized_words) > size:
            candidate = ' '.join(normalized_words[:size])
            if candidate in candidates:
                return candidate, ' '.join(normalized_words[size:])

    return None, stem


def looks_like_title_fragment(text: str) -> bool:
    words = set(re.findall(r"[a-z0-9']+", normalize_text(text).lower()))
    return any(token in words for token in ('official', 'video', 'audio', 'live', 'acoustic', 'unplugged', 'lyrics', 'lyric'))


def extract_track_and_title(title: str) -> tuple[int | None, str]:
    match = re.match(r'^(?P<prefix>.+?)\s+-\s+(?P<track>\d{1,2})\s+-\s+(?P<name>.+)$', title)
    if match:
        return int(match.group('track')), clean_title(match.group('name'))
    return None, title


def infer_artist_title_with_separator(left: str, right: str) -> tuple[str | None, str]:
    left_artist = normalize_artist(strip_trailing_youtube_id(left))
    right_artist = normalize_artist(strip_trailing_youtube_id(right))
    left_title = clean_title(left)
    right_title = clean_title(right)

    if left_artist in KNOWN_ARTISTS and right_artist not in KNOWN_ARTISTS:
        return left_artist, right_title

    if right_artist in KNOWN_ARTISTS and left_artist not in KNOWN_ARTISTS:
        return right_artist, left_title

    for separator in (' - ', ' – '):
        if separator in right:
            middle, candidate_artist_raw = right.rsplit(separator, 1)
            candidate_artist = normalize_artist(strip_trailing_youtube_id(candidate_artist_raw))
            if candidate_artist in KNOWN_ARTISTS:
                middle_title = clean_title(middle)
                combined_title = left_title if not middle_title else f'{left_title} - {middle_title}'
                return candidate_artist, combined_title

    if looks_like_title_fragment(left) and right_artist and len(right_artist.split()) <= 4:
        return right_artist, left_title

    return left_artist, right_title


def parse_filename(path: Path) -> dict[str, str | int | None]:
    stem = path.stem
    track_number: int | None = None

    match = TRACK_PREFIX_RE.match(stem)
    if match:
        track_number = int(match.group('track'))
        stem = match.group('rest')

    artist: str | None = None
    title = clean_title(stem)
    for separator in SEPARATOR_CANDIDATES:
        if separator in stem:
            left, right = stem.split(separator, 1)
            artist, title = infer_artist_title_with_separator(left, right)
            break

    if not artist:
        artist_guess, title_guess = infer_artist_title_without_separator(stem)
        artist = artist_guess
        title = clean_title(title_guess)

    inferred_track, cleaned_title = extract_track_and_title(title)
    if track_number is None and inferred_track is not None:
        track_number = inferred_track
        title = cleaned_title

    if not title:
        title = normalize_text(path.stem)

    return {
        'artist': artist,
        'title': title,
        'tracknumber': track_number,
    }


def ensure_mp3_tags(path: Path) -> EasyID3:
    try:
        return EasyID3(path)
    except ID3NoHeaderError:
        audio = MP3(path)
        audio.add_tags()
        audio.save()
        return EasyID3(path)


def write_tags(path: Path, artist: str | None, title: str, tracknumber: int | None, album: str | None) -> None:
    suffix = path.suffix.lower()

    if suffix == '.mp3':
        tags = ensure_mp3_tags(path)
        if title:
            tags['title'] = [title]
        if artist:
            tags['artist'] = [artist]
            tags['albumartist'] = [artist]
        if tracknumber is not None:
            tags['tracknumber'] = [str(tracknumber)]
        if album:
            tags['album'] = [album]
        tags.save(v2_version=3)
        return

    audio = MutagenFile(path, easy=True)
    if audio is None:
        raise RuntimeError(f'Formato no soportado por mutagen: {path}')

    if title:
        audio['title'] = [title]
    if artist:
        audio['artist'] = [artist]
        try:
            audio['albumartist'] = [artist]
        except Exception:
            pass
    if tracknumber is not None:
        audio['tracknumber'] = [str(tracknumber)]
    if album:
        audio['album'] = [album]
    audio.save()


def title_without_artist_prefix(raw_title: str, artist: str | None) -> str:
    candidate = normalize_text(strip_trailing_youtube_id(raw_title))
    if not candidate or not artist:
        return candidate

    artist_key = normalize_key(artist)
    for separator in SEPARATOR_CANDIDATES:
        if separator in candidate:
            left, right = candidate.split(separator, 1)
            if normalize_key(left) == artist_key:
                return normalize_text(strip_trailing_youtube_id(right))

    candidate_words = candidate.split()
    artist_words = normalize_text(artist).split()
    if len(candidate_words) > len(artist_words):
        left_key = [normalize_key(word) for word in candidate_words[:len(artist_words)]]
        artist_word_keys = [normalize_key(word) for word in artist_words]
        if left_key == artist_word_keys:
            return ' '.join(candidate_words[len(artist_words):])

    return candidate


def build_rename_title(path: Path, artist: str | None, title: str, raw_title: str | None) -> str:
    if raw_title:
        parsed = parse_filename(Path(f'{raw_title}{path.suffix}'))
        parsed_artist = parsed.get('artist')
        parsed_title = parsed.get('title')
        if artist and isinstance(parsed_artist, str) and normalize_key(parsed_artist) == normalize_key(artist) and isinstance(parsed_title, str) and parsed_title:
            return parsed_title

        candidate = title_without_artist_prefix(raw_title, artist)
        if candidate:
            if ' -- ' in raw_title and title and normalize_key(title) != normalize_key(candidate):
                return title
            return candidate

    stem = path.stem
    match = TRACK_PREFIX_RE.match(stem)
    if match:
        stem = match.group('rest')

    candidate = title_without_artist_prefix(stem, artist)
    if candidate:
        return candidate

    return title


def build_new_name(path: Path, artist: str | None, title: str, tracknumber: int | None, raw_title: str | None = None) -> str:
    rename_title = build_rename_title(path, artist, title, raw_title)
    video_id = extract_youtube_id(path.stem)
    stem = f'{artist} - {rename_title}' if artist else rename_title
    if video_id:
        stem = f'{stem}-{video_id}'
    stem = re.sub(r'[\/:*?"<>|]', '_', stem)
    return f'{stem}{path.suffix.lower()}'

def extract_youtube_id(stem: str) -> str | None:
    cleaned = stem.strip()
    match = TRAILING_YOUTUBE_ID_RE.search(cleaned)
    if match:
        return match.group('id')
    match = YOUTUBE_ID_RE.fullmatch(cleaned)
    if match:
        return match.group('id')
    return None


def fetch_youtube_oembed(video_id: str) -> dict[str, object] | None:
    params = urlencode({
        'url': f'https://www.youtube.com/watch?v={video_id}',
        'format': 'json',
    })
    request = Request(f'{YOUTUBE_OEMBED_URL}?{params}', headers={'User-Agent': MUSICBRAINZ_USER_AGENT})
    with urlopen(request, timeout=20) as response:
        return json.load(response)



def title_case_known_artist(raw: str) -> str | None:
    artist = normalize_artist(raw)
    return artist if artist else None


def infer_artist_from_youtube_title(raw_title: str, raw_author: str) -> str | None:
    normalized_title = normalize_text(raw_title)
    normalized_author = normalize_artist(raw_author.replace(' - Topic', '').strip())

    if ' - ' in normalized_title or ' – ' in normalized_title:
        parsed = parse_filename(Path(normalized_title))
        parsed_artist = parsed.get('artist')
        if isinstance(parsed_artist, str) and parsed_artist:
            return parsed_artist

    if normalized_author and raw_author.endswith(' - Topic'):
        return normalized_author

    return None


def resolve_with_youtube(path: Path) -> tuple[str | None, str | None, str | None]:
    video_id = extract_youtube_id(path.stem)
    if not video_id:
        return None, None, None

    override_artist = YOUTUBE_ID_ARTIST_OVERRIDES.get(video_id)

    try:
        payload = fetch_youtube_oembed(video_id)
    except (HTTPError, URLError, TimeoutError, OSError) as exc:
        print(f'[youtube-error] {path} -> {exc}', file=sys.stderr)
        return None, None, None

    if not payload:
        return None, None, None

    raw_title = str(payload.get('title') or '').strip()
    raw_author = str(payload.get('author_name') or '').strip()
    parsed = parse_filename(Path(f'{raw_title}{path.suffix}')) if raw_title else {'artist': None, 'title': None, 'tracknumber': None}

    artist = override_artist or infer_artist_from_youtube_title(raw_title, raw_author)
    title = parsed.get('title') if parsed.get('title') else (clean_title(raw_title) if raw_title else None)

    print(f'[youtube] {path} -> artist={artist!r} title={title!r} source_title={raw_title!r} source_author={raw_author!r}')
    return artist if isinstance(artist, str) else None, title if isinstance(title, str) else None, raw_title or None

def get_audio_duration_ms(path: Path) -> int | None:
    try:
        audio = MutagenFile(path)
    except Exception:
        return None
    if audio is None or not getattr(audio, 'info', None):
        return None
    length = getattr(audio.info, 'length', None)
    if length is None:
        return None
    return int(length * 1000)


def normalize_key(text: str) -> str:
    return re.sub(r'[^a-z0-9]+', '', normalize_text(text).casefold())


def artist_credit_name(recording: dict) -> str | None:
    credits = recording.get('artist-credit') or []
    parts: list[str] = []
    for item in credits:
        if isinstance(item, str):
            parts.append(item)
            continue
        name = item.get('name') or item.get('artist', {}).get('name')
        if name:
            parts.append(name)
        join = item.get('joinphrase')
        if join:
            parts.append(join)
    artist = ''.join(parts).strip()
    return artist or None


def fetch_musicbrainz_candidates(title: str, duration_ms: int | None, limit: int) -> list[dict[str, object]]:
    escaped_title = title.replace(chr(92), chr(92) * 2).replace(chr(34), chr(92) + chr(34))
    query = f'recording:"{escaped_title}"'
    params = urlencode({'query': query, 'fmt': 'json', 'limit': str(limit)})
    request = Request(f'{MUSICBRAINZ_API_URL}?{params}', headers={'User-Agent': MUSICBRAINZ_USER_AGENT})
    with urlopen(request, timeout=20) as response:
        payload = json.load(response)

    title_key = normalize_key(title)
    candidates: list[dict[str, object]] = []
    for recording in payload.get('recordings', []):
        artist = artist_credit_name(recording)
        if not artist:
            continue
        candidate_title = recording.get('title') or ''
        length = recording.get('length')
        delta_ms = abs(int(length) - duration_ms) if duration_ms is not None and length is not None else None
        exact_title = normalize_key(candidate_title) == title_key
        candidates.append({
            'artist': normalize_artist(artist),
            'title': candidate_title,
            'score': int(recording.get('score', 0)),
            'length_ms': int(length) if length is not None else None,
            'delta_ms': delta_ms,
            'exact_title': exact_title,
        })

    candidates.sort(key=lambda item: (
        not bool(item['exact_title']),
        item['delta_ms'] is None,
        item['delta_ms'] if item['delta_ms'] is not None else 10**12,
        -int(item['score']),
        str(item['artist'] or ''),
    ))
    return candidates


def should_auto_apply_musicbrainz(candidate: dict[str, object]) -> bool:
    if not candidate.get('artist'):
        return False
    if not candidate.get('exact_title'):
        return False
    if int(candidate.get('score', 0)) < 95:
        return False
    delta_ms = candidate.get('delta_ms')
    if delta_ms is None:
        return True
    return int(delta_ms) <= 4000


def choose_artist_with_musicbrainz(path: Path, title: str, album: str | None, limit: int, auto_apply: bool) -> str | None:
    duration_ms = get_audio_duration_ms(path)
    try:
        candidates = fetch_musicbrainz_candidates(title, duration_ms, limit)
    except (HTTPError, URLError, TimeoutError, OSError) as exc:
        print(f'[musicbrainz-error] {path} -> {exc}', file=sys.stderr)
        return None

    if not candidates:
        print(f'[musicbrainz-none] {path} -> title={title!r} album={album!r}')
        return None

    if auto_apply and should_auto_apply_musicbrainz(candidates[0]):
        chosen = candidates[0]['artist']
        print(f'[musicbrainz-auto] {path} -> artist={chosen!r} title={title!r}')
        return chosen if isinstance(chosen, str) else None

    print(f'\n[musicbrainz] {path}')
    print(f'  titulo={title!r} album={album!r} duracion_ms={duration_ms!r}')
    for index, candidate in enumerate(candidates, start=1):
        delta_ms = candidate['delta_ms']
        delta_text = '?' if delta_ms is None else f'{int(delta_ms) / 1000:.1f}s'
        print(
            f'  {index}. artist={candidate["artist"]!r} title={candidate["title"]!r} '
            f'score={candidate["score"]} delta={delta_text}'
        )

    while True:
        choice = input('Elegí número, Enter para omitir, o escribí un artista manual: ').strip()
        if not choice:
            return None
        if choice.isdigit():
            idx = int(choice) - 1
            if 0 <= idx < len(candidates):
                artist = candidates[idx]['artist']
                return artist if isinstance(artist, str) else None
        else:
            manual = normalize_artist(choice)
            if manual:
                return manual
        print('Entrada inválida.')


def main() -> int:
    args = parse_args()
    root = Path(args.folder).expanduser().resolve()

    if not root.exists() or not root.is_dir():
        print(f'Carpeta inválida: {root}', file=sys.stderr)
        return 1

    changed = 0
    skipped = 0
    errors = 0
    missing_artist = 0

    for path in iter_audio_files(root):
        parsed = parse_filename(path)
        artist = parsed['artist']
        title = parsed['title']
        tracknumber = parsed['tracknumber']
        album = infer_album_from_parent(path.parent.name, args.force_album_from_parent)
        rename_source_title: str | None = None

        if not title:
            print(f'[skip] No pude inferir título: {path}')
            skipped += 1
            continue

        if args.youtube_assist:
            parsed_artist = artist
            youtube_artist, youtube_title, youtube_raw_title = resolve_with_youtube(path)
            same_artist = bool(parsed_artist and youtube_artist and normalize_key(parsed_artist) == normalize_key(youtube_artist))
            if youtube_raw_title and (not parsed_artist or same_artist):
                rename_source_title = youtube_raw_title
            if not artist and youtube_artist:
                artist = youtube_artist
            if youtube_title and (not parsed_artist or same_artist):
                title = youtube_title

        if not artist and args.musicbrainz_assist:
            artist = choose_artist_with_musicbrainz(path, title, album, args.musicbrainz_limit, args.musicbrainz_auto_apply)

        summary = f'artist={artist!r} title={title!r} track={tracknumber!r} album={album!r}'
        if not artist:
            missing_artist += 1
            print(f'[needs-artist] {path} -> title={title!r} album={album!r}')

        try:
            if args.dry_run:
                print(f'[dry-run] {path} -> {summary}')
            else:
                write_tags(path, artist, title, tracknumber, album)
                print(f'[ok] {path} -> {summary}')
                changed += 1

            if args.rename and artist:
                new_name = build_new_name(path, artist, title, tracknumber, rename_source_title)
                new_path = path.with_name(new_name)
                if new_path != path:
                    if args.dry_run:
                        print(f'         rename -> {new_path.name}')
                    else:
                        path.rename(new_path)
                        print(f'         renamed -> {new_path.name}')
        except Exception as exc:
            print(f'[error] {path}: {exc}', file=sys.stderr)
            errors += 1

    print(f'\nResumen: changed={changed} skipped={skipped} errors={errors} missing_artist={missing_artist}')
    return 1 if errors else 0


if __name__ == '__main__':
    raise SystemExit(main())
