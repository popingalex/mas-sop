# SAFE 框架贡献指南

## 1. 引言

欢迎对 SAFE (Strategist, Awareness, Field Expert, Executor) 框架做出贡献！您的帮助对于改进和扩展这个用于应急响应规划辅助的多智能体框架至关重要。本指南提供了为 SAFE 项目贡献代码所需的信息。

我们鼓励各种形式的贡献，包括但不限于：

*   报告 Bug (Bug Reports)
*   提交功能请求 (Feature Requests)
*   改进文档 (Documentation Improvements)
*   添加新的智能体角色 (Agent Roles)、动作 (Actions) 或工具 (Tools)
*   编写测试 (Tests)
*   代码重构 (Code Refactoring)

## 2. 开始之前

*   **熟悉项目**: 请先阅读 `README.md` 和 `01_framework_overview.md` 来理解 SAFE 框架的目标和架构。
*   **查看现有议题 (Issues)**: 浏览 GitHub 上的议题列表，看看是否有人已经报告了您发现的问题或提出了类似的功能请求。
*   **加入讨论 (可选)**: 如果您有新的想法或想讨论潜在的变更，可以在 GitHub Discussions 或相关的议题中发起对话。

## 3. 开发环境设置

1.  **Fork 仓库**: 在 GitHub 上 Fork (派生) SAFE 框架的主仓库。
2.  **Clone 您的 Fork**: 将您派生的仓库克隆到本地机器：
    ```bash
    git clone https://github.com/YOUR_USERNAME/safe-framework.git # 替换为您的用户名
    cd safe-framework
    ```
3.  **设置虚拟环境**: 强烈建议使用虚拟环境。我们推荐使用 Conda：
    ```bash
    # 确保您已安装 Miniconda 或 Anaconda
    # 使用指定的 Python 版本 (例如 3.9, < 3.12)
    conda create -n safe-dev python=3.9
    conda activate safe-dev
    ```
    或者使用 `venv`:
    ```bash
    python -m venv .venv
    # 在 Windows 上激活
    .venv\Scripts\activate
    # 在 macOS/Linux 上激活
    source .venv/bin/activate
    ```
4.  **安装依赖**: 安装核心依赖项和开发依赖项：
    ```bash
    pip install -r requirements.txt
    pip install -r requirements-dev.txt # (如果存在开发依赖文件)
    ```
5.  **设置预提交钩子 (Pre-commit Hooks)**: 我们使用 `pre-commit` 来强制执行代码风格和质量检查。安装并设置它：
    ```bash
    pip install pre-commit
    pre-commit install
    ```
    这将在您每次提交代码时自动运行检查 (如 Black, Flake8, isort)。

## 4. 编码规范

*   **代码风格 (Code Style)**: 我们遵循 PEP 8 标准，并使用 Black 进行代码格式化，isort 进行导入排序。
*   **类型提示 (Type Hinting)**: 请为所有函数和方法添加类型提示。
*   **文档字符串 (Docstrings)**: 为所有公共模块、类、函数和方法编写清晰的文档字符串 (遵循 Google 风格或 NumPy 风格)。
*   **日志记录 (Logging)**: 使用 Python 内置的 `logging` 模块进行日志记录，而不是 `print()` 语句。
*   **测试 (Testing)**: 为您添加或修改的代码编写单元测试 (Unit Tests) 或集成测试 (Integration Tests)。我们使用 `pytest` 作为测试框架。

## 5. 贡献流程

1.  **创建分支 (Branch)**: 从 `main` (或当前的开发分支) 创建一个新的特性分支 (Feature Branch)：
    ```bash
    git checkout main
    git pull origin main
    git checkout -b feature/your-descriptive-feature-name # 或 fix/your-bug-fix-name
    ```
2.  **进行修改 (Make Changes)**: 实现您的功能或修复 Bug。确保遵循编码规范。
3.  **编写测试 (Write Tests)**: 添加必要的测试用例以覆盖您的代码。
4.  **运行测试 (Run Tests)**: 确保所有测试通过：
    ```bash
    pytest
    ```
5.  **运行预提交检查 (Run Pre-commit Checks)**: 在提交前手动运行检查 (虽然 `pre-commit install` 会自动运行)：
    ```bash
    pre-commit run --all-files
    ```
    修复任何报告的问题。
6.  **提交更改 (Commit Changes)**: 编写清晰、简洁的提交消息 (Commit Message)。遵循 Conventional Commits 约定是一个好主意 (例如, `feat: Add new RiskAnalysis action`, `fix: Correct artifact naming in Executor`)。
    ```bash
    git add .
    git commit -m "feat: Your descriptive commit message"
    ```
7.  **推送分支 (Push Branch)**: 将您的分支推送到您的 Fork：
    ```bash
    git push origin feature/your-descriptive-feature-name
    ```
8.  **创建拉取请求 (Pull Request - PR)**: 在 GitHub 上，导航到您的 Fork，然后点击 "Compare & pull request"。选择主仓库的 `main` 分支作为目标分支。
    *   为您的 PR 提供一个清晰的标题和描述。
    *   如果您的 PR 解决了某个议题 (Issue)，请在描述中链接该议题 (例如, `Closes #123`)。
    *   确保所有 CI/CD 检查通过。
9.  **代码审查 (Code Review)**: 项目维护者将审查您的代码。请准备好根据反馈进行修改。
10. **合并 (Merge)**: 一旦您的 PR 被批准并且所有检查都通过，维护者会将其合并到主分支。

## 6. 行为准则 (Code of Conduct)

请注意，本项目遵循贡献者行为准则 (Contributor Covenant Code of Conduct)。我们期望所有贡献者和参与者都能遵守这些准则，以营造一个开放和欢迎的环境。

感谢您为 SAFE 框架做出的贡献！ 