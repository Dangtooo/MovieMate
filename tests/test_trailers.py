from backend.tmdb import get_movie_details, select_trailer


def video(key='official_key', **kwargs):
    return {'site': 'YouTube', 'type': 'Trailer', 'key': key, **kwargs}


def test_english_fallback_keeps_vietnamese_metadata(monkeypatch):
    calls = []
    original = {'id': 1, 'title': 'Tên tiếng Việt', 'original_language': 'ja', 'videos': {'results': []}}
    def get(path, **params):
        calls.append((path, params))
        return original if path == 'movie/1' else {'results': [video()]}
    monkeypatch.setattr('backend.tmdb.tmdb_get', get)
    result = get_movie_details(1)
    assert result['title'] == 'Tên tiếng Việt'
    assert result['videos']['results'][0]['key'] == 'official_key'
    assert calls[1] == ('movie/1/videos', {'language': 'en'})
    assert original['videos']['results'] == []


def test_original_language_fallback_and_official_priority(monkeypatch):
    calls = []
    def get(path, **params):
        calls.append(params.get('language'))
        if path == 'movie/1':
            return {'id': 1, 'original_language': 'ko', 'videos': {'results': []}}
        return {'results': [] if params['language'] == 'en' else [video('unofficial'), video(official=True)]}
    monkeypatch.setattr('backend.tmdb.tmdb_get', get)
    assert select_trailer(get_movie_details(1)['videos']['results'])['key'] == 'official_key'
    assert calls == [None, 'en', 'ko']


def test_vietnamese_trailer_needs_no_extra_request(monkeypatch):
    calls = []
    def get(path, **params):
        calls.append(path)
        return {'videos': {'results': [video()]}}
    monkeypatch.setattr('backend.tmdb.tmdb_get', get)
    get_movie_details(1)
    assert calls == ['movie/1']
    assert select_trailer([video(type='Teaser')]) is None
