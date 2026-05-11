from fastapi import FastAPI, Request, Response, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.sessions import SessionMiddleware
import xml.etree.ElementTree as ET
import aiosqlite
import os
from datetime import datetime
app = FastAPI()

app.add_middleware(SessionMiddleware, secret_key=os.urandom(24).hex())

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

DB_PATH = "example.db"

@app.on_event("startup")
async def startup():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("CREATE TABLE IF NOT EXISTS users (id TEXT PRIMARY KEY, pw TEXT)")
        await db.execute("""
            CREATE TABLE IF NOT EXISTS posts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT,
                date TEXT,
                time TEXT,
                content TEXT,
                preview TEXT
            )
        """)
        await db.execute("INSERT OR IGNORE INTO users VALUES ('admin', '1234')")
        await db.commit()

def get_nexacro_value(xml_str: str, target_id: str):
    try:
        root = ET.fromstring(xml_str)
        ns = {'ns': 'http://www.nexacroplatform.com/platform/dataset'}
        param = root.find(f".//ns:Parameter[@id='{target_id}']", ns)
        if param is not None: return param.text
    except: pass
    return None

def make_nexacro_xml_response(xml_str: str):
    return Response(content=xml_str, media_type="application/xml")

def create_error_xml(code: int, msg: str):
    return f"""<?xml version="1.0" encoding="utf-8"?>
<Root xmlns="http://www.nexacroplatform.com/platform/dataset">
    <Parameters>
        <Parameter id="ErrorCode" type="int">{code}</Parameter>
        <Parameter id="ErrorMsg" type="string">{msg}</Parameter>
    </Parameters>
</Root>"""

@app.post("/login")
async def login(request: Request):
    raw_data = (await request.body()).decode("utf-8")
    user_id = get_nexacro_value(raw_data, 'id')
    user_pw = get_nexacro_value(raw_data, 'pw')

    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("SELECT id FROM users WHERE id = ? AND pw = ?", (user_id, user_pw))
        user = await cursor.fetchone()

    if user:
        request.session['user_id'] = user_id
        request.session['is_logged_in'] = True
        xml_res = create_error_xml(0, "로그인 성공")
    else:
        xml_res = create_error_xml(-1, "아이디/비밀번호 확인 요망")
    
    return make_nexacro_xml_response(xml_res)

@app.api_route("/posts", methods=["GET", "POST"])
async def select_posts(request: Request):
    if not request.session.get('is_logged_in'):
        return make_nexacro_xml_response(create_error_xml(-2, "세션 만료"))

    rows_xml = ""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT id, title, date, time, preview FROM posts") as cursor:
            async for row in cursor:
                rows_xml += f"""
        <Row>
            <Col id="id">{row['id']}</Col>
            <Col id="title">{row['title']}</Col>
            <Col id="date">{row['date']}</Col>
            <Col id="time">{row['time']}</Col>
            <Col id="preview">{row['preview']}</Col>
        </Row>"""

    xml_data = f"""<?xml version="1.0" encoding="utf-8"?>
<Root xmlns="http://nexacroplatform.com">
    <Parameters>
        <Parameter id="ErrorCode" type="int">0</Parameter>
        <Parameter id="ErrorMsg" type="string">success</Parameter>
    </Parameters>
    <Dataset id="Post">
        <ColumnInfo>
            <Column id="id" type="INT" size="256" />
            <Column id="title" type="STRING" size="256" />
            <Column id="date" type="STRING" size="256" />
            <Column id="time" type="STRING" size="256" />
            <Column id="preview" type="STRING" size="256" />
        </ColumnInfo>
        <Rows>{rows_xml}</Rows>
    </Dataset>
</Root>"""
    return make_nexacro_xml_response(xml_data)

@app.post("/posts/save")
async def save_post(request: Request):
    if not request.session.get('is_logged_in'):
        return make_nexacro_xml_response(create_error_xml(-2, "timeout"))
    raw_data = (await request.body()).decode("utf-8")
    p_id = get_nexacro_value(raw_data, 'id')
    p_title = get_nexacro_value(raw_data, 'title')
    p_content = get_nexacro_value(raw_data, 'content')
    p_preview = (p_content[:50] + "...") if p_content and len(p_content) > 50 else p_content
    now = datetime.now()
    p_date, p_time = now.strftime("%Y-%m-%d"), now.strftime("%H:%M")
    async with aiosqlite.connect(DB_PATH) as db:
        if p_id:
            await db.execute("UPDATE posts SET title=?, content=?, preview=?, date=?, time=? WHERE id=?", (p_title, p_content, p_preview, p_date, p_time, p_id))
        else:
            await db.execute("INSERT INTO posts (title, date, time, content, preview) VALUES (?,?,?,?,?)", (p_title, p_date, p_time, p_content, p_preview))
        await db.commit()
    return make_nexacro_xml_response(create_error_xml(0, "success"))

@app.post("/posts/read")
async def read_post(request: Request):
    if not request.session.get('is_logged_in'):
        return make_nexacro_xml_response(create_error_xml(-2, "timeout"))
    
    body = (await request.body()).decode("utf-8")
    p_id = get_nexacro_value(body, 'postId')
    
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT title, content FROM posts WHERE id = ?", (p_id,))
        row = await cursor.fetchone()
        
    if row:
        row_xml = f"""
        <Row>
            <Col id="title">{row['title']}</Col>
            <Col id="content">{row['content']}</Col>
        </Row>"""
        
        xml = f"""<?xml version="1.0" encoding="utf-8"?>
<Root xmlns="http://nexacroplatform.com">
    <Parameters>
        <Parameter id="ErrorCode" type="int">0</Parameter>
    </Parameters>
    <Dataset id="DetailPost">
        <ColumnInfo>
            <Column id="title" type="STRING" size="256" />
            <Column id="content" type="STRING" size="4000" />
        </ColumnInfo>
        <Rows>
            {row_xml}
        </Rows>
    </Dataset>
</Root>"""
        return make_nexacro_xml_response(xml)
    
    return make_nexacro_xml_response(create_error_xml(-1, "not found"))


@app.post("/signup")
async def signup(request: Request):
    raw_data = (await request.body()).decode("utf-8")
    user_id = get_nexacro_value(raw_data, 'id')
    user_pw = get_nexacro_value(raw_data, 'pw')

    if not user_id or not user_pw:
        return make_nexacro_xml_response(create_error_xml(-1, "입력값 누락"))

    async with aiosqlite.connect(DB_PATH) as db:
        try:
            await db.execute("INSERT INTO users (id, pw) VALUES (?, ?)", (user_id, user_pw))
            await db.commit()
            xml_res = create_error_xml(0, "회원가입 완료")
        except aiosqlite.IntegrityError:
            xml_res = create_error_xml(-1, "아이디 중복")
    
    return make_nexacro_xml_response(xml_res)

if __name__ == '__main__':
    import uvicorn
    uvicorn.run(app, host='127.0.0.1', port=8000)
