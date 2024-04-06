from flask import Flask, render_template, request, redirect, url_for, session
from flask_socketio import SocketIO, emit, join_room, leave_room
from flask_sqlalchemy import SQLAlchemy
from flask_cors import CORS
from openai import OpenAI
from dotenv import load_dotenv
import os

# Next two lines are for the issue: https://github.com/miguelgrinberg/python-engineio/issues/142
from engineio.payload import Payload
Payload.max_decode_packets = 200

app = Flask(__name__)
load_dotenv()
CORS(app)
app.config['SECRET_KEY'] = "thisismys3cr3tk3yrree"
app.config['SQLALCHEMY_DATABASE_URI'] = 'postgresql://default:5lRaUgW1bLzo@ep-square-wind-a4xxqxcv-pooler.us-east-1.aws.neon.tech/verceldb?sslmode=require'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
client = OpenAI(api_key=os.getenv('OPENAI_KEY'))

db = SQLAlchemy(app)


from werkzeug.security import generate_password_hash, check_password_hash
from sqlalchemy.exc import IntegrityError, OperationalError


user_word = db.Table('userk_word',
                     db.Column('id', db.Integer, primary_key=True),
                     db.Column('userk_id', db.Integer, db.ForeignKey('userk.id')),
                     db.Column('word_id', db.Integer, db.ForeignKey('word.id'))
                     )


class Word(db.Model):
    __tablename__ = 'word'
    id = db.Column(db.Integer(), primary_key=True)
    org_word = db.Column(db.String(150), nullable=False)
    trans_word = db.Column(db.String(50), nullable=False)

    def __repr__(self):
        return f'<Word "{self.id}">'

    @classmethod
    def get_word_by_kaz_word(cls, kaz_word):
        return cls.query.filter_by(kaz_word=kaz_word).all()

    @classmethod
    def get_word_by_trans_word(cls, trans_word):
        return cls.query.filter_by(trans_word=trans_word).all()

    def save(self):
        db.session.add(self)
        db.session.commit()

    def delete(self):
        db.session.delete(self)
        db.session.commit()


class Userk(db.Model):
    __tablename__ = 'userk'
    id = db.Column(db.Integer(), primary_key=True)
    email = db.Column(db.String(150), nullable=False)
    firstname = db.Column(db.String(50), nullable=False)
    lastname = db.Column(db.String(50), nullable=False)
    language = db.Column(db.String(100))
    password = db.Column(db.Text)
    words = db.relationship('Word', secondary=user_word, backref='words')

    def __repr__(self):
        return f'<User "{self.id}">'

    def set_password(self, password):
        self.password = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password, password)

    @classmethod
    def get_user_by_email(cls, email):
        return cls.query.filter_by(email=email).first()

    @classmethod
    def update_email(cls, email, new_email, password):
        user = cls.query.filter_by(email=email).first()
        if user and user.check_password(password):
            user.email = new_email
            try:
                db.session.commit()
                return True
            except (IntegrityError, OperationalError):
                db.session.rollback()
                return False
        return False

    @classmethod
    def update_password(cls, email, password, new_password):
        user = cls.get_user_by_email(email)
        if user and user.check_password(password):
            try:
                user.set_password(new_password)
                db.session.commit()
                return True
            except (IntegrityError, OperationalError):
                db.session.rollback()
        return False

    def save(self):
        db.session.add(self)
        db.session.commit()

    def delete(self):
        db.session.delete(self)
        db.session.commit()


class Room(db.Model):
    __tablename__ = 'room'
    room_id = db.Column(db.String(), primary_key=True)
    username = db.Column(db.String(), primary_key=True)
    language = db.Column(db.String(), primary_key=True)
    language_level = db.Column(db.Integer(), primary_key=True)

    def __repr__(self):
        return f'<Room "{self.room_id}"'

    @classmethod
    def find_suitable_room(cls, language, language_level):
        if language == 'kaz':
            need_language = 'eng'
        else:
            need_language = 'kaz'

        room = cls.query.filter_by(language=need_language, language_level=language_level).first()
        # filtered_rooms = list(filter(lambda ro: ro.language_level == language_level and ro.language == need_language, rooms))
        if room is not None:
            room.delete()
            return room
        return None

    def save(self):
        db.session.add(self)
        db.session.commit()

    def delete(self):
        db.session.delete(self)
        db.session.commit()


socketio = SocketIO(app)

_users_in_room = {}  # stores room wise user list
_room_of_sid = {}  # stores room joined by a used
_name_of_sid = {}  # stores display name of users


@app.route("/", methods=["GET", "POST"])
def index():
    return render_template("index.html")


@app.route("/set/language", methods=["GET", "POST"])
def set_language():
    return render_template("setlang.html")


@app.route('/testkaz', methods=["GET", "POST"])
def test_kaz():
    return render_template('testkaz.html')


@app.route('/testeng', methods=["GET", "POST"])
def test_eng():
    return render_template('testeng.html')


@app.route("/signup", methods=['GET', 'POST'])
def sign_up():
    if request.method == "POST":
        new_userk = Userk(
            email=request.form['email'],
            firstname=request.form['firstname'],
            lastname=request.form['lastname'],
            language=request.form['language']
        )
        new_userk.set_password(password=request.form['password'])
        new_userk.save()
        session['UserEmail'] = new_userk.email
        if request.form['language'] == 'kaz':
            return redirect(url_for(endpoint="test_kaz"))
        else:
            return redirect(url_for(endpoint="test_eng"))
    return render_template("signup.html")


@app.route("/find/companion/<string:username>/<string:language>/<int:language_level>/", methods=["GET", "POST"])
def find_companion(username, language, language_level):
    room = Room.find_suitable_room(language=language, language_level=language_level)  # todo: companion should be one level higher
    if room:
        return redirect(url_for(endpoint="enter_room", room_id=room.room_id, language=language))
    else:
        room_id = os.urandom(5).hex()
        new_room = Room(
            room_id=room_id,
            username=username,
            language=language,
            language_level=language_level
        )
        new_room.save()
        return redirect(url_for(endpoint="entry_checkpoint", room_id=room_id, language=language))


@app.route("/room/<string:room_id>/<string:language>/")
def enter_room(room_id, language):
    if room_id not in session:
        return redirect(url_for("entry_checkpoint", room_id=room_id, language=language))
    prompt = f"дай только пять вопросов на {language} для начало и развите разгавора с другим человеком инстранцом в видео звонке."
    response = client.chat.completions.create(  # Этот метод отправляет запрос на сервер OpenAI и возвращает ответ.
        model="gpt-4-turbo-preview",
        messages=[
            {"role": "user", "content": prompt}
        ]
    )
    txt = response.choices[0].message.content
    txt = txt.split('\n')
    return render_template("chatroom.html",
                           room_id=room_id,
                           display_name=session[room_id]["name"],
                           mute_audio=session[room_id]["mute_audio"],
                           mute_video=session[room_id]["mute_video"],
                           questions=txt)


@app.route("/room/<string:room_id>/<string:language>/checkpoint/", methods=["GET", "POST"])
def entry_checkpoint(room_id, language):
    if request.method == "POST":
        display_name = request.form['display_name']
        mute_audio = request.form['mute_audio']
        mute_video = request.form['mute_video']
        session[room_id] = {"name": display_name, "language": language, "mute_audio": mute_audio, "mute_video": mute_video}
        return redirect(url_for("enter_room", room_id=room_id, language=language))
    return render_template("chatroom_checkpoint.html", room_id=room_id)


@socketio.on("connect")
def on_connect():
    sid = request.sid
    print("New socket connected ", sid)
    

@socketio.on("join-room")
def on_join_room(data):
    sid = request.sid
    room_id = data["room_id"]
    display_name = session[room_id]["name"]
    
    # register sid to the room
    join_room(room_id)
    _room_of_sid[sid] = room_id
    _name_of_sid[sid] = display_name
    
    # broadcast to others in the room
    print("[{}] New member joined: {}<{}>".format(room_id, display_name, sid))
    emit("user-connect", {"sid": sid, "name": display_name}, broadcast=True, include_self=False, room=room_id)
    
    # add to user list maintained on server
    if room_id not in _users_in_room:
        _users_in_room[room_id] = [sid]
        emit("user-list", {"my_id": sid})   # send own id only
    else:
        usrlist = {u_id: _name_of_sid[u_id] for u_id in _users_in_room[room_id]}
        emit("user-list", {"list": usrlist, "my_id": sid})  # send list of existing users to the new member
        _users_in_room[room_id].append(sid)  # add new member to user list maintained on server

    print("\nusers: ", _users_in_room, "\n")


@socketio.on("disconnect")
def on_disconnect():
    sid = request.sid
    room_id = _room_of_sid[sid]
    display_name = _name_of_sid[sid]

    print("[{}] Member left: {}<{}>".format(room_id, display_name, sid))
    emit("user-disconnect", {"sid": sid}, broadcast=True, include_self=False, room=room_id)

    _users_in_room[room_id].remove(sid)
    if len(_users_in_room[room_id]) == 0:
        _users_in_room.pop(room_id)

    _room_of_sid.pop(sid)
    _name_of_sid.pop(sid)

    print("\nusers: ", _users_in_room, "\n")


@socketio.on("data")
def on_data(data):
    sender_sid = data['sender_id']
    target_sid = data['target_id']
    if sender_sid != request.sid:
        print("[Not supposed to happen!] request.sid and sender_id don't match!!!")

    if data["type"] != "new-ice-candidate":
        print('{} message from {} to {}'.format(data["type"], sender_sid, target_sid))
    socketio.emit('data', data, room=target_sid)


if __name__ == "__main__":
    # with app.app_context():
    #     db.drop_all()
    # with app.app_context():
    #     db.create_all()
    socketio.run(app, debug=True)
