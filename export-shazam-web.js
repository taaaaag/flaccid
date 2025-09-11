
// JS-Console script to export song name, artist and cover image URL to a JSON format
// Order of results is in ascending date order. If you want to change that, delete line with '.reverse()'
// The result is copied to your clipboard
// 
// 1. Open https://www.shazam.com/myshazam and login
// 2. Scroll down to the end of your list, so that *all* songs are loaded
// 3. Open Developer console with F12
// 4. Copy paste this code to the JS-console and hit Enter
// 5. Paste the result to your favorite text editor. Voilà.

// Output JSON looks like
// {
//   "meta": {
//     "scriptUrl": "https://gist.github.com/hennzen/dc2b7bb76ce5507063f6c5e60c68886a",
//     "scriptRevision": "0.0.3",
//     "listCreated": "2020-09-27T07:40:06.184Z"
//   },
//   "shazamItems": [
//     {
//       "no": 1,
//       "title": "Dancing With The Damned",
//       "artist": "Killing Mood",
//       "cover": "https://images.shazam.com/coverart/t50270807-b333557118_s400.jpg",
//       "availableOnAppleMusicPlay": true
//     }
//   ]
// }
copy ({
    meta: {
        scriptUrl: "https://gist.github.com/hennzen/dc2b7bb76ce5507063f6c5e60c68886a",
        scriptRevision: "0.0.3",
        listCreated: new Date().toISOString()
    },
    shazamItems: Array.from(document.querySelectorAll('.shazams-content ul.panel-bd.panel-bd-wide .track'))
        .reverse() // delete this line for date descending order
        .map((item, index) => ({
            no: index + 1,
            title: item.querySelector('.title').innerText,
            artist: item.querySelector('.artist').innerText,
            cover: item.querySelector('.image.album-art').style['background-image'].match(/"(.*?)"/)[1],
            availableOnAppleMusicPlay: item.querySelector('article').getAttribute("data-shz-applemusicplay-id").length ? true: false
        }))
});
