from flask import Flask, render_template, jsonify, request, session, redirect, url_for, flash, send_file
from flask_sqlalchemy import SQLAlchemy
import os
import pandas as pd
from collections import Counter
import jieba
import re
import shutil
from datetime import datetime
from functools import wraps
from werkzeug.security import generate_password_hash, check_password_hash
import socket

app = Flask(__name__)
app.secret_key = 'your-secret-key-here'  # 用于session加密

# 配置SQLite数据库
basedir = os.path.abspath(os.path.dirname(__file__))
db_path = os.path.join(basedir, 'faq.db')

# 确保数据目录存在
os.makedirs(os.path.dirname(db_path), exist_ok=True)

app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + db_path
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SQLALCHEMY_ECHO'] = False  # 生产环境关闭SQL日志

# 设置URL前缀
URL_PREFIX = '/mzfaq'  # 门诊FAQ的拼音缩写

# 配置上传目录
UPLOAD_FOLDER = os.path.join(basedir, 'uploads')
STATIC_FOLDER = os.path.join(basedir, 'static')
BACKUP_FOLDER = os.path.join(basedir, 'backups')

# 确保必要的目录存在
for folder in [UPLOAD_FOLDER, STATIC_FOLDER, BACKUP_FOLDER]:
    os.makedirs(folder, exist_ok=True)

db = SQLAlchemy(app)

# 管理员账户信息
ADMIN_USERNAME = 'admin'
ADMIN_PASSWORD = generate_password_hash('admin123')  # 设置默认密码

# 登录验证装饰器
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'logged_in' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

# 定义要过滤的停用词
STOP_WORDS = {'是', '的', '吗', '么', '或者', '什么', '怎么', '如何', '哪位', '可以', '需要', '没有', '有', '是否', 
              '通过', '一般', '都', '给', '到', '在', '和', '及', '与', '以及', '还有', '一个', '是什么', '为', '了',
              '被', '将', '向', '让', '使', '用', '对', '能', '高', '低', '中', '上', '下', '前', '后', '内', '外',
              '会', '要', '去', '来', '做', '看', '听', '说', '想', '这个', '那个', '这样', '那样', '就', '才', '把',
              '从', '但是', '但', '而且', '而', '所以', '因此', '如果', '的话', '只是', '只有', '还是', '还', '又',
              '也', '已经', '已', '现在', '马上', '立即', '即将', '将要', '打算', '准备', '计划', '比较', '非常'}

# 添加自定义词典
CUSTOM_WORDS = {
    # 电商平台和应用（权重15）
    '山姆': 15,
    '京东': 15,
    '大众点评': 15,
    '字节跳动': 15,
    '高德': 15,
    '快手': 15,
    '微商城': 15,

    # 金融相关（权重14）
    '平安银行': 14,
    '银行': 14,
    '招白金': 14,
    '保险': 14,
    '医保': 14,
    '报销': 14,

    # 医疗服务（权重13）
    '医疗预约': 13,
    '洗牙': 13,
    '洁牙': 13,
    '预约': 13,
    '未到诊': 13,
    '福芽': 13,

    # 就医流程（权重12）
    '门诊': 12,
    '挂号': 12,
    '就医': 12,
    '诊疗': 12,
    '检查': 12,
    '治疗': 12,
    '转诊': 12,
    '复诊': 12,

    # 医务人员（权重11）
    '医生': 11,
    '护士': 11,
    '专家': 11,

    # 费用相关（权重10）
    '挂号费': 10,
    '诊疗费': 10,
    '检查费': 10,
    '治疗费': 10,
    '药费': 10,

    # 其他（权重9）
    '病人': 9,
    '患者': 9,
    '医院': 9,
    '诊所': 9,
    '科室': 9
}

# 添加自定义词典
for word, weight in CUSTOM_WORDS.items():
    jieba.add_word(word, freq=weight)

# 数据库备份函数
def backup_database():
    """创建数据库备份"""
    try:
        backup_dir = BACKUP_FOLDER
        if not os.path.exists(backup_dir):
            os.makedirs(backup_dir)
        
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        backup_file = os.path.join(backup_dir, f'faq_backup_{timestamp}.db')
        
        # 确保数据库文件存在
        db_file = db_path
        if os.path.exists(db_file):
            shutil.copy2(db_file, backup_file)
            
            # 只保留最近的5个备份
            backups = sorted([f for f in os.listdir(backup_dir) if f.startswith('faq_backup_')])
            if len(backups) > 5:
                for old_backup in backups[:-5]:
                    os.remove(os.path.join(backup_dir, old_backup))
            return True
        return False
    except Exception as e:
        print(f"备份数据库时出错: {str(e)}")
        return False

# 定义FAQ模型
class FAQ(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    question = db.Column(db.String(500), nullable=False)
    answer = db.Column(db.Text, nullable=False)

    def to_dict(self):
        return {
            'id': self.id,
            'question': self.question,
            'answer': self.answer
        }

# 在应用启动时创建必要的目录
with app.app_context():
    # 删除旧的数据库文件（如果存在）
    if os.path.exists(db_path):
        os.remove(db_path)
    
    # 确保上传和静态文件目录存在
    os.makedirs(UPLOAD_FOLDER, exist_ok=True)
    os.makedirs(STATIC_FOLDER, exist_ok=True)
    
    # 重新创建数据库表
    db.create_all()
    
    # 导入Excel数据
    if not FAQ.query.first():  # 如果数据库为空，则导入数据
        try:
            excel_file = '门诊常见问题汇总.xlsx'
            print(f"正在读取Excel文件: {excel_file}")
            df = pd.read_excel(excel_file)
            print("Excel列名:", df.columns.tolist())
            
            for index, row in df.iterrows():
                try:
                    question = str(row['问题']).strip()
                    answer = str(row['答案']).strip()
                    
                    if pd.notna(question) and pd.notna(answer):
                        faq = FAQ(
                            question=question,
                            answer=answer
                        )
                        db.session.add(faq)
                        print(f"添加问题: {question}")
                        print(f"答案: {answer}")
                        print("-" * 50)
                except Exception as row_error:
                    print(f"处理第{index+1}行时出错: {row_error}")
                    continue
            
            db.session.commit()
            print("数据导入完成")
            
            # 验证数据是否成功导入
            all_faqs = FAQ.query.all()
            print(f"数据库中的问题总数: {len(all_faqs)}")
            for faq in all_faqs[:3]:  # 打印前3个问题作为示例
                print(f"ID: {faq.id}")
                print(f"问题: {faq.question}")
                print(f"答案: {faq.answer}")
                print("-" * 50)
                
        except Exception as e:
            print(f"导入数据时出错: {str(e)}")
            print("当前工作目录:", os.getcwd())
            print("Excel文件是否存在:", os.path.exists('门诊常见问题汇总.xlsx'))

def clean_text(text):
    """清理文本，去除特殊字符和多余空格"""
    # 替换特殊字符为空格
    text = re.sub(r'[^\w\s\u4e00-\u9fff]', ' ', text)
    # 替换多个空格为单个空格
    text = re.sub(r'\s+', ' ', text)
    return text.strip()

def extract_keywords(text):
    """提取关键词的改进版本"""
    # 清理文本
    text = clean_text(text)
    
    # 使用精确模式进行分词
    words = jieba.cut(text, cut_all=False)
    
    # 过滤停用词和单字词，保留自定义词典中的词
    words = [word for word in words if (
        word not in STOP_WORDS and 
        (len(word) > 1 or word in CUSTOM_WORDS)
    )]
    
    return words

def get_hot_questions():
    """获取热门问题列表"""
    faqs = FAQ.query.all()
    # 这里可以根据实际需求设置热门问题的选择逻辑
    # 当前简单返回前5个问题
    hot_questions = faqs[:5]
    return [{
        'id': faq.id,
        'question': faq.question
    } for faq in hot_questions]

# 主页路由 - 公开访问
@app.route(URL_PREFIX + '/')
def home():
    faqs = FAQ.query.all()  # 获取所有FAQ数据
    hot_questions = get_hot_questions()
    return render_template('index.html', faqs=faqs, hot_questions=hot_questions)

@app.route(URL_PREFIX + '/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        
        if username == ADMIN_USERNAME and check_password_hash(ADMIN_PASSWORD, password):
            session['logged_in'] = True
            return redirect(url_for('admin'))
        else:
            flash('用户名或密码错误')
    
    return render_template('login.html')

@app.route(URL_PREFIX + '/logout')
def logout():
    session.pop('logged_in', None)
    return redirect(url_for('home'))

# 以下是管理员功能，需要登录
@app.route(URL_PREFIX + '/admin')
@login_required
def admin():
    faqs = FAQ.query.all()  # 获取所有FAQ数据
    return render_template('admin.html', faqs=faqs)

# 搜索API - 公开访问
@app.route(URL_PREFIX + '/api/search', methods=['GET'])
def search_faqs():
    try:
        query = request.args.get('q', '').strip()
        if not query:
            return jsonify([])
            
        # 使用简单的模糊匹配
        faqs = FAQ.query.filter(
            db.or_(
                FAQ.question.ilike(f'%{query}%'),
                FAQ.answer.ilike(f'%{query}%')
            )
        ).all()
        
        return jsonify([faq.to_dict() for faq in faqs])
    except Exception as e:
        print(f"搜索出错: {str(e)}")
        return jsonify({'error': str(e)}), 500

# 获取所有FAQ - 公开访问
@app.route(URL_PREFIX + '/api/faqs', methods=['GET'])
def get_faqs():
    try:
        print("开始获取FAQ数据...")
        faqs = FAQ.query.all()
        print(f"从数据库获取到 {len(faqs)} 条记录")
        return jsonify([faq.to_dict() for faq in faqs])
    except Exception as e:
        print(f"获取FAQ数据时出错: {str(e)}")
        return jsonify({'error': str(e)}), 500

# 获取单个FAQ - 公开访问
@app.route(URL_PREFIX + '/api/faqs/<int:id>', methods=['GET'])
def get_faq(id):
    try:
        faq = FAQ.query.get_or_404(id)
        return jsonify(faq.to_dict())
    except Exception as e:
        return jsonify({'error': str(e)}), 404

@app.route(URL_PREFIX + '/api/faqs/keywords', methods=['GET'])
def get_keywords():
    """获取关键词的API端点"""
    faqs = FAQ.query.all()
    all_keywords = []
    
    for faq in faqs:
        # 处理问题
        question_keywords = extract_keywords(faq.question)
        all_keywords.extend(question_keywords)
        
        # 处理答案中的关键信息
        answer_keywords = extract_keywords(faq.answer)
        all_keywords.extend(answer_keywords)
    
    # 统计关键词频率
    keyword_counter = Counter(all_keywords)
    
    # 应用自定义词典中的权重
    for word in CUSTOM_WORDS:
        if word in keyword_counter:
            keyword_counter[word] *= CUSTOM_WORDS[word]
    
    # 按频率排序并返回前25个关键词
    sorted_keywords = sorted(
        [(k, v) for k, v in keyword_counter.items()],
        key=lambda x: x[1],
        reverse=True
    )[:25]
    
    # 返回关键词列表
    result = [kw[0] for kw in sorted_keywords]
    return jsonify(result)

@app.route(URL_PREFIX + '/api/faqs', methods=['POST'])
@login_required
def add_faq():
    try:
        print("开始添加新FAQ")
        data = request.get_json()
        
        if not data:
            print("错误：未收到数据")
            return jsonify({
                'status': 'error',
                'message': '没有接收到数据'
            }), 400
            
        print(f"收到的数据: {data}")
        
        # 验证必要字段
        if 'question' not in data or 'answer' not in data:
            print("错误：缺少必要字段")
            return jsonify({
                'status': 'error',
                'message': '数据格式错误：缺少问题或答案字段'
            }), 400
        
        # 验证字段不为空
        question = str(data['question']).strip()
        answer = str(data['answer']).strip()
        
        if not question or not answer:
            print("错误：问题或答案为空")
            return jsonify({
                'status': 'error',
                'message': '问题和答案不能为空'
            }), 400
            
        # 验证字段长度
        if len(question) < 2 or len(question) > 500:
            print("错误：问题长度不符合要求")
            return jsonify({
                'status': 'error',
                'message': '问题长度必须在2-500字符之间'
            }), 400
            
        if len(answer) < 2:
            print("错误：答案长度不符合要求")
            return jsonify({
                'status': 'error',
                'message': '答案长度必须大于2个字符'
            }), 400
            
        try:
            # 创建新FAQ
            new_faq = FAQ(
                question=question,
                answer=answer
            )
            
            # 添加到数据库
            db.session.add(new_faq)
            db.session.commit()
            
            print(f"成功添加FAQ，ID={new_faq.id}")
            return jsonify({
                'status': 'success',
                'message': '添加成功',
                'data': new_faq.to_dict()
            }), 201
            
        except Exception as e:
            print(f"保存到数据库时出错: {str(e)}")
            db.session.rollback()
            return jsonify({
                'status': 'error',
                'message': f'保存失败: {str(e)}'
            }), 500
            
    except Exception as e:
        print(f"添加FAQ时出错: {str(e)}")
        return jsonify({
            'status': 'error',
            'message': f'添加失败: {str(e)}'
        }), 500

@app.route(URL_PREFIX + '/api/upload', methods=['POST'])
@login_required
def upload_faqs():
    try:
        print("开始处理文件上传请求...")
        
        if 'file' not in request.files:
            print("错误：请求中没有文件")
            return jsonify({
                'status': 'error',
                'message': '没有上传文件'
            }), 400
            
        file = request.files['file']
        if not file or not file.filename:
            print("错误：没有选择文件")
            return jsonify({
                'status': 'error',
                'message': '没有选择文件'
            }), 400
            
        if not file.filename.endswith(('.xlsx', '.xls')):
            print(f"错误：文件格式不正确 - {file.filename}")
            return jsonify({
                'status': 'error',
                'message': '请上传Excel文件(.xlsx或.xls格式)'
            }), 400

        # 保存上传的文件
        upload_path = UPLOAD_FOLDER
        if not os.path.exists(upload_path):
            os.makedirs(upload_path)
        file_path = os.path.join(upload_path, 'temp_upload.xlsx')
        
        print(f"保存上传文件到: {file_path}")
        file.save(file_path)
        
        try:
            # 读取Excel文件
            print(f"开始读取Excel文件: {file_path}")
            df = pd.read_excel(file_path, engine='openpyxl')
            print(f"Excel文件列名: {df.columns.tolist()}")
            
            if '问题' not in df.columns or '答案' not in df.columns:
                print("错误：Excel文件格式错误，缺少必要的列")
                os.remove(file_path)
                return jsonify({
                    'status': 'error',
                    'message': 'Excel文件格式错误：必须包含"问题"和"答案"列'
                }), 400
            
            # 备份数据库
            print("开始备份数据库...")
            if not backup_database():
                print("错误：数据库备份失败")
                os.remove(file_path)
                return jsonify({
                    'status': 'error',
                    'message': '数据库备份失败，导入已取消'
                }), 500
            
            # 导入数据
            success_count = 0
            error_count = 0
            error_details = []
            
            print(f"开始导入数据，共 {len(df)} 条记录")
            for index, row in df.iterrows():
                try:
                    question = str(row['问题']).strip() if pd.notna(row['问题']) else ''
                    answer = str(row['答案']).strip() if pd.notna(row['答案']) else ''
                    
                    # 验证数据
                    if not question or not answer:
                        error_count += 1
                        error_details.append(f"第 {index+1} 行: 问题或答案为空")
                        continue
                        
                    if len(question) < 2 or len(question) > 500:
                        error_count += 1
                        error_details.append(f"第 {index+1} 行: 问题长度必须在2-500字符之间")
                        continue
                        
                    if len(answer) < 2:
                        error_count += 1
                        error_details.append(f"第 {index+1} 行: 答案长度必须大于2个字符")
                        continue
                    
                    faq = FAQ(
                        question=question,
                        answer=answer
                    )
                    db.session.add(faq)
                    success_count += 1
                    print(f"成功导入第 {index+1} 条记录")
                except Exception as e:
                    error_count += 1
                    error_details.append(f"第 {index+1} 行: {str(e)}")
                    print(f"错误：导入第 {index+1} 行时出错: {str(e)}")
                    continue
            
            if success_count > 0:
                print("提交数据库事务...")
                db.session.commit()
                print("数据库事务提交成功")
            else:
                print("没有成功导入的记录，回滚事务")
                db.session.rollback()
                
            # 删除临时文件
            if os.path.exists(file_path):
                os.remove(file_path)
                print("已删除临时文件")
            
            message = f'成功导入 {success_count} 个问题'
            if error_count > 0:
                message += f'，{error_count} 个问题导入失败'
                if error_details:
                    message += f'\n详细错误信息：\n' + '\n'.join(error_details)
            
            if success_count == 0:
                return jsonify({
                    'status': 'error',
                    'message': message
                }), 400
            
            print(f"导入完成: {message}")
            return jsonify({
                'status': 'success',
                'message': message
            })
            
        except Exception as e:
            print(f"处理Excel文件时出错: {str(e)}")
            db.session.rollback()
            if os.path.exists(file_path):
                os.remove(file_path)
            raise e
        
    except Exception as e:
        print(f"导入Excel时出错: {str(e)}")
        return jsonify({
            'status': 'error',
            'message': f'导入失败: {str(e)}'
        }), 500

@app.route(URL_PREFIX + '/api/backup', methods=['POST'])
@login_required
def create_backup():
    if backup_database():
        return jsonify({
            'status': 'success',
            'message': '数据库备份成功'
        })
    return jsonify({
        'status': 'error',
        'message': '数据库备份失败'
    }), 500

@app.route(URL_PREFIX + '/api/faqs/<int:faq_id>', methods=['DELETE'])
@login_required
def delete_faq(faq_id):
    try:
        faq = FAQ.query.get_or_404(faq_id)
        db.session.delete(faq)
        db.session.commit()
        return jsonify({
            'status': 'success',
            'message': '问题删除成功'
        })
    except Exception as e:
        db.session.rollback()
        return jsonify({
            'status': 'error',
            'message': f'删除失败: {str(e)}'
        }), 500

@app.route('/mzfaq/api/faqs/<int:id>/question', methods=['DELETE'])
@login_required
def delete_question(id):
    try:
        faq = FAQ.query.get_or_404(id)
        faq.question = ''  # 只清空问题，保留答案
        db.session.commit()
        return jsonify({'status': 'success', 'message': '问题已删除'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/mzfaq/api/faqs/<int:id>/answer', methods=['DELETE'])
@login_required
def delete_answer(id):
    try:
        faq = FAQ.query.get_or_404(id)
        faq.answer = ''  # 只清空答案，保留问题
        db.session.commit()
        return jsonify({'status': 'success', 'message': '答案已删除'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route(URL_PREFIX + '/api/faqs/<int:id>', methods=['PUT'])
@login_required
def update_faq(id):
    try:
        print(f"开始更新FAQ, ID={id}")
        faq = FAQ.query.get_or_404(id)
        data = request.get_json()
        
        if not data:
            print("未收到更新数据")
            return jsonify({'error': '没有接收到数据'}), 400
        
        print(f"收到更新数据: {data}")
        
        if 'question' not in data or 'answer' not in data:
            print("数据格式错误：缺少必要字段")
            return jsonify({'error': '数据格式错误：缺少必要字段'}), 400
        
        faq.question = data['question']
        faq.answer = data['answer']
        
        try:
            db.session.commit()
            print(f"成功更新FAQ: ID={id}")
            return jsonify(faq.to_dict())
        except Exception as e:
            print(f"保存更新时出错: {str(e)}")
            db.session.rollback()
            raise
            
    except Exception as e:
        print(f"更新FAQ时出错 (ID={id}): {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route(URL_PREFIX + '/admin/template')
@login_required
def download_template():
    try:
        # 创建示例数据
        data = {
            '问题': [
                '如何预约挂号？',
                '就诊需要带什么证件？',
                '门诊开放时间是什么时候？'
            ],
            '答案': [
                '您可以通过以下方式预约挂号：1. 医院官方网站 2. 微信公众号 3. 医院APP 4. 电话预约',
                '请携带：1. 身份证 2. 医保卡（如有） 3. 预约单号（如有预约）',
                '门诊一般时间为：周一至周五 8:00-17:00，周六周日 8:00-12:00。具体科室可能会有调整，请以当天公告为准。'
            ]
        }
        
        # 创建DataFrame
        df = pd.DataFrame(data)
        
        # 创建临时文件
        template_path = os.path.join(STATIC_FOLDER, 'template.xlsx')
        
        # 确保static目录存在
        os.makedirs(os.path.dirname(template_path), exist_ok=True)
        
        # 导出到Excel文件
        df.to_excel(template_path, index=False, engine='openpyxl')
        
        # 返回文件下载响应
        return send_file(
            template_path,
            as_attachment=True,
            download_name='FAQ导入模板.xlsx',
            mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        )
        
    except Exception as e:
        print(f"下载模板时出错: {str(e)}")
        return jsonify({
            'status': 'error',
            'message': f'下载模板失败: {str(e)}'
        }), 500

@app.route(URL_PREFIX + '/admin/export')
@login_required
def export_faqs():
    try:
        # 从数据库获取所有FAQ数据
        faqs = FAQ.query.all()
        
        # 创建DataFrame
        data = {
            '问题': [faq.question for faq in faqs],
            '答案': [faq.answer for faq in faqs]
        }
        df = pd.DataFrame(data)
        
        # 创建一个临时文件来保存Excel
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = f'FAQ导出_{timestamp}.xlsx'
        export_path = os.path.join(STATIC_FOLDER, filename)
        
        # 导出到Excel文件
        df.to_excel(export_path, index=False, engine='openpyxl')
        
        # 返回文件下载响应
        return send_file(
            export_path,
            as_attachment=True,
            download_name=filename,
            mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        )
        
    except Exception as e:
        print(f"导出Excel时出错: {str(e)}")
        return jsonify({
            'status': 'error',
            'message': f'导出失败: {str(e)}'
        }), 500

@app.route(URL_PREFIX + '/admin/import', methods=['POST'])
@login_required
def import_excel():
    try:
        if 'file' not in request.files:
            return jsonify({
                'status': 'error',
                'message': '没有上传文件'
            }), 400
            
        file = request.files['file']
        if not file or not file.filename:
            return jsonify({
                'status': 'error',
                'message': '没有选择文件'
            }), 400
            
        if not file.filename.endswith(('.xlsx', '.xls')):
            return jsonify({
                'status': 'error',
                'message': '请上传Excel文件(.xlsx或.xls格式)'
            }), 400

        # 确保上传目录存在
        upload_dir = UPLOAD_FOLDER
        if not os.path.exists(upload_dir):
            os.makedirs(upload_dir)

        # 保存上传的文件
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = f'upload_{timestamp}.xlsx'
        file_path = os.path.join(upload_dir, filename)
        file.save(file_path)
        
        try:
            # 读取Excel文件
            df = pd.read_excel(file_path, engine='openpyxl')
            
            if '问题' not in df.columns or '答案' not in df.columns:
                os.remove(file_path)
                return jsonify({
                    'status': 'error',
                    'message': 'Excel文件格式错误：必须包含"问题"和"答案"列'
                }), 400
            
            # 备份数据库
            if not backup_database():
                os.remove(file_path)
                return jsonify({
                    'status': 'error',
                    'message': '数据库备份失败，导入已取消'
                }), 500
            
            # 导入数据
            success_count = 0
            error_count = 0
            
            for _, row in df.iterrows():
                try:
                    question = str(row['问题']).strip() if pd.notna(row['问题']) else ''
                    answer = str(row['答案']).strip() if pd.notna(row['答案']) else ''
                    
                    if question and answer:  # 确保问题和答案不为空
                        faq = FAQ(
                            question=question,
                            answer=answer
                        )
                        db.session.add(faq)
                        success_count += 1
                    else:
                        error_count += 1
                except Exception as e:
                    error_count += 1
                    print(f"导入行时出错: {str(e)}")
                    continue
            
            db.session.commit()
            
            # 清理临时文件
            os.remove(file_path)
            
            message = f'成功导入 {success_count} 个问题'
            if error_count > 0:
                message += f'，{error_count} 个问题导入失败'
            
            return jsonify({
                'status': 'success',
                'message': message
            })
            
        except Exception as e:
            # 发生错误时回滚数据库并清理临时文件
            db.session.rollback()
            if os.path.exists(file_path):
                os.remove(file_path)
            raise e
        
    except Exception as e:
        print(f"导入Excel时出错: {str(e)}")
        return jsonify({
            'status': 'error',
            'message': f'导入失败: {str(e)}'
        }), 500

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port) 