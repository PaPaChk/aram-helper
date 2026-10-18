; *** Inno Setup version 6.5.0+ Chinese Simplified messages ***
;
; To download user-contributed translations of this file, go to:
;   https://jrsoftware.org/files/istrans/
;
; Note: When translating this text, do not add periods (.) to the end of
; messages that didn't have them already, because on those messages Inno
; Setup adds the periods automatically (appending a period would result in
; two periods being displayed).
;
; Maintained by Zhenghan Yang
; Email: 847320916@QQ.com
; Translation based on network resource
; The latest Translation is on https://github.com/kira-96/Inno-Setup-Chinese-Simplified-Translation
;

[LangOptions]
; The following three entries are very important. Be sure to read and 
; understand the '[LangOptions] section' topic in the help file.
LanguageName=簡體中文
; If Language Name display incorrect, uncomment next line
; LanguageName=<7B80><4F53><4E2D><6587>
; About LanguageID, to reference link:
; https://docs.microsoft.com/en-us/openspecs/windows_protocols/ms-lcid/a9eac961-e77d-41a6-90a5-ce1a8b0cdb9c
LanguageID=$0804
; About CodePage, to reference link:
; https://docs.microsoft.com/en-us/windows/win32/intl/code-page-identifiers
LanguageCodePage=936
; If the language you are translating to requires special font faces or
; sizes, uncomment any of the following entries and change them accordingly.
;DialogFontName=
;DialogFontSize=9
;DialogFontBaseScaleWidth=7
;DialogFontBaseScaleHeight=15
;WelcomeFontName=Segoe UI
;WelcomeFontSize=14

[Messages]

; *** 應用程式標題
SetupAppTitle=安裝
SetupWindowTitle=安裝 - %1
UninstallAppTitle=解除安裝
UninstallAppFullTitle=%1 解除安裝

; *** Misc. common
InformationTitle=資訊
ConfirmTitle=確認
ErrorTitle=錯誤

; *** SetupLdr messages
SetupLdrStartupMessage=現在將安裝 %1。您想要繼續嗎？
LdrCannotCreateTemp=無法建立臨時檔案。安裝程式已中止
LdrCannotExecTemp=無法執行臨時目錄中的檔案。安裝程式已中止
HelpTextNote=

; *** 啟動錯誤訊息
LastErrorMessage=%1。%n%n錯誤 %2: %3
SetupFileMissing=安裝目錄中缺少檔案 %1。請修正這個問題或者獲取程式的新副本。
SetupFileCorrupt=安裝檔案已損壞。請獲取程式的新副本。
SetupFileCorruptOrWrongVer=安裝檔案已損壞，或是與這個安裝程式的版本不相容。請修正這個問題或獲取新的程式副本。
InvalidParameter=無效的命令列引數：%n%n%1
SetupAlreadyRunning=安裝程式正在執行。
WindowsVersionNotSupported=此程式不支援當前計算機執行的 Windows 版本。
WindowsServicePackRequired=此程式需要 %1 服務包 %2 或更高版本。
NotOnThisPlatform=此程式不能在 %1 上執行。
OnlyOnThisPlatform=此程式只能在 %1 上執行。
OnlyOnTheseArchitectures=此程式只能安裝到為下列處理器架構設計的 Windows 版本中：%n%n%1
WinVersionTooLowError=此程式需要 %1 版本 %2 或更高。
WinVersionTooHighError=此程式不能安裝於 %1 版本 %2 或更高。
AdminPrivilegesRequired=在安裝此程式時您必須以管理員身份登入。
PowerUserPrivilegesRequired=在安裝此程式時您必須以管理員身份或有許可權的使用者組身份登入。
SetupAppRunningError=安裝程式發現 %1 當前正在執行。%n%n請先關閉正在執行的程式，然後點選“確定”繼續，或點選“取消”退出。
UninstallAppRunningError=解除安裝程式發現 %1 當前正在執行。%n%n請先關閉正在執行的程式，然後點選“確定”繼續，或點選“取消”退出。

; *** 啟動問題
PrivilegesRequiredOverrideTitle=選擇安裝程式模式
PrivilegesRequiredOverrideInstruction=選擇安裝模式
PrivilegesRequiredOverrideText1=%1 可以為所有使用者安裝(需要管理員許可權)，或僅為您安裝。
PrivilegesRequiredOverrideText2=%1 可以僅為您安裝，或為所有使用者安裝(需要管理員許可權)。
PrivilegesRequiredOverrideAllUsers=為所有使用者安裝(&A)
PrivilegesRequiredOverrideAllUsersRecommended=為所有使用者安裝(&A) (建議選項)
PrivilegesRequiredOverrideCurrentUser=僅為我安裝(&M)
PrivilegesRequiredOverrideCurrentUserRecommended=僅為我安裝(&M) (建議選項)

; *** 其他錯誤
ErrorCreatingDir=安裝程式無法建立目錄“%1”
ErrorTooManyFilesInDir=無法在目錄“%1”中建立檔案，因為裡面包含太多檔案

; *** 安裝程式公共訊息
ExitSetupTitle=退出安裝程式
ExitSetupMessage=安裝程式尚未完成。如果現在退出，將不會安裝該程式。%n%n您之後可以再次執行安裝程式完成安裝。%n%n現在退出安裝程式嗎？
AboutSetupMenuItem=關於安裝程式(&A)...
AboutSetupTitle=關於安裝程式
AboutSetupMessage=%1 版本 %2%n%3%n%n%1 主頁：%n%4
AboutSetupNote=
TranslatorNote=簡體中文翻譯由Kira(847320916@qq.com)維護。專案地址：https://github.com/kira-96/Inno-Setup-Chinese-Simplified-Translation

; *** 按鈕
ButtonBack=< 上一步(&B)
ButtonNext=下一步(&N) >
ButtonInstall=安裝(&I)
ButtonOK=確定
ButtonCancel=取消
ButtonYes=是(&Y)
ButtonYesToAll=全是(&A)
ButtonNo=否(&N)
ButtonNoToAll=全否(&O)
ButtonFinish=完成(&F)
ButtonBrowse=瀏覽(&B)...
ButtonWizardBrowse=瀏覽(&R)...
ButtonNewFolder=新建資料夾(&M)

; *** “選擇語言”對話方塊訊息
SelectLanguageTitle=選擇安裝語言
SelectLanguageLabel=選擇安裝時使用的語言。

; *** 公共嚮導文字
ClickNext=點選“下一步”繼續，或點選“取消”退出安裝程式。
BeveledLabel=
BrowseDialogTitle=瀏覽資料夾
BrowseDialogLabel=在下面的列表中選擇一個資料夾，然後點選“確定”。
NewFolderName=新建資料夾

; *** “歡迎”嚮導頁
WelcomeLabel1=歡迎使用 [name] 安裝嚮導
WelcomeLabel2=現在將安裝 [name/ver] 到您的電腦中。%n%n建議您在繼續安裝前關閉所有其他應用程式。

; *** “密碼”嚮導頁
WizardPassword=密碼
PasswordLabel1=這個安裝程式有密碼保護。
PasswordLabel3=請輸入密碼，然後點選“下一步”繼續。密碼區分大小寫。
PasswordEditLabel=密碼(&P)：
IncorrectPassword=您輸入的密碼不正確，請重新輸入。

; *** “許可協議”嚮導頁
WizardLicense=許可協議
LicenseLabel=請在繼續安裝前閱讀以下重要資訊。
LicenseLabel3=請仔細閱讀下列許可協議。在繼續安裝前您必須同意這些協議條款。
LicenseAccepted=我同意此協議(&A)
LicenseNotAccepted=我不同意此協議(&D)

; *** “資訊”嚮導頁
WizardInfoBefore=資訊
InfoBeforeLabel=請在繼續安裝前閱讀以下重要資訊。
InfoBeforeClickLabel=準備好繼續安裝後，點選“下一步”。
WizardInfoAfter=資訊
InfoAfterLabel=請在繼續安裝前閱讀以下重要資訊。
InfoAfterClickLabel=準備好繼續安裝後，點選“下一步”。

; *** “使用者資訊”嚮導頁
WizardUserInfo=使用者資訊
UserInfoDesc=請輸入您的資訊。
UserInfoName=使用者名稱(&U)：
UserInfoOrg=組織(&O)：
UserInfoSerial=序列號(&S)：
UserInfoNameRequired=您必須輸入使用者名稱。

; *** “選擇目標目錄”嚮導頁
WizardSelectDir=選擇目標位置
SelectDirDesc=您想將 [name] 安裝在哪裡？
SelectDirLabel3=安裝程式將安裝 [name] 到下面的資料夾中。
SelectDirBrowseLabel=點選“下一步”繼續。如果您想選擇其他資料夾，點選“瀏覽”。
DiskSpaceGBLabel=至少需要有 [gb] GB 的可用磁碟空間。
DiskSpaceMBLabel=至少需要有 [mb] MB 的可用磁碟空間。
CannotInstallToNetworkDrive=安裝程式無法安裝到一個網路驅動器。
CannotInstallToUNCPath=安裝程式無法安裝到一個 UNC 路徑。
InvalidPath=您必須輸入一個帶驅動器卷標的完整路徑，例如：%n%nC:\APP%n%n或UNC路徑：%n%n\\server\share
InvalidDrive=您選定的驅動器或 UNC 共享不存在或不能訪問。請選擇其他位置。
DiskSpaceWarningTitle=磁碟空間不足
DiskSpaceWarning=安裝程式至少需要 %1 KB 的可用空間才能安裝，但選定驅動器只有 %2 KB 的可用空間。%n%n您一定要繼續嗎？
DirNameTooLong=資料夾名稱或路徑太長。
InvalidDirName=資料夾名稱無效。
BadDirName32=資料夾名稱不能包含下列任何字元：%n%n%1
DirExistsTitle=資料夾已存在
DirExists=資料夾：%n%n%1%n%n已經存在。您一定要安裝到這個資料夾中嗎？
DirDoesntExistTitle=資料夾不存在
DirDoesntExist=資料夾：%n%n%1%n%n不存在。您想要建立此資料夾嗎？

; *** “選擇元件”嚮導頁
WizardSelectComponents=選擇元件
SelectComponentsDesc=您想安裝哪些程式元件？
SelectComponentsLabel2=選中您想安裝的元件；取消您不想安裝的元件。然後點選“下一步”繼續。
FullInstallation=完全安裝
; if possible don't translate 'Compact' as 'Minimal' (I mean 'Minimal' in your language)
CompactInstallation=簡潔安裝
CustomInstallation=自定義安裝
NoUninstallWarningTitle=元件已存在
NoUninstallWarning=安裝程式檢測到下列元件已安裝在您的電腦中：%n%n%1%n%n取消選中這些元件不會解除安裝它們。%n%n確定要繼續嗎？
ComponentSize1=%1 KB
ComponentSize2=%1 MB
ComponentsDiskSpaceGBLabel=當前選擇的元件需要至少 [gb] GB 的磁碟空間。
ComponentsDiskSpaceMBLabel=當前選擇的元件需要至少 [mb] MB 的磁碟空間。

; *** “選擇附加任務”嚮導頁
WizardSelectTasks=選擇附加任務
SelectTasksDesc=您想要安裝程式執行哪些附加任務？
SelectTasksLabel2=選擇您想要安裝程式在安裝 [name] 時執行的附加任務，然後點選“下一步”。

; *** “選擇開始選單資料夾”嚮導頁
WizardSelectProgramGroup=選擇開始選單資料夾
SelectStartMenuFolderDesc=安裝程式應該在哪裡放置程式的快捷方式？
SelectStartMenuFolderLabel3=安裝程式將在下列“開始”選單資料夾中建立程式的快捷方式。
SelectStartMenuFolderBrowseLabel=點選“下一步”繼續。如果您想選擇其他資料夾，點選“瀏覽”。
MustEnterGroupName=您必須輸入一個資料夾名。
GroupNameTooLong=資料夾名或路徑太長。
InvalidGroupName=無效的資料夾名字。
BadGroupName=資料夾名不能包含下列任何字元：%n%n%1
NoProgramGroupCheck2=不建立開始選單資料夾(&D)

; *** “準備安裝”嚮導頁
WizardReady=準備安裝
ReadyLabel1=安裝程式準備就緒，現在可以開始安裝 [name] 到您的電腦。
ReadyLabel2a=點選“安裝”繼續此安裝程式。如果您想重新考慮或修改任何設定，點選“上一步”。
ReadyLabel2b=點選“安裝”繼續此安裝程式。
ReadyMemoUserInfo=使用者資訊：
ReadyMemoDir=目標位置：
ReadyMemoType=安裝型別：
ReadyMemoComponents=已選擇元件：
ReadyMemoGroup=開始選單資料夾：
ReadyMemoTasks=附加任務：

; *** TExtractionWizardPage 嚮導頁面與 ExtractArchive
ExtractingLabel=正在解壓檔案...
ButtonStopExtraction=停止解壓(&S)
StopExtraction=您確定要停止解壓嗎？
ErrorExtractionAborted=解壓已中止
ErrorExtractionFailed=解壓失敗：%1

; *** 壓縮檔案解壓失敗詳情
ArchiveIncorrectPassword=壓縮檔案密碼不正確
ArchiveIsCorrupted=壓縮檔案已損壞
ArchiveUnsupportedFormat=不支援的壓縮檔案格式

; *** TDownloadWizardPage 嚮導頁面和 DownloadTemporaryFile
DownloadingLabel2=正在下載檔案...
ButtonStopDownload=停止下載(&S)
StopDownload=您確定要停止下載嗎？
ErrorDownloadAborted=下載已中止
ErrorDownloadFailed=下載失敗：%1 %2
ErrorDownloadSizeFailed=獲取下載大小失敗：%1 %2
ErrorProgress=無效的進度：%1 / %2
ErrorFileSize=檔案大小錯誤：預期 %1，實際 %2

; *** “正在準備安裝”嚮導頁
WizardPreparing=正在準備安裝
PreparingDesc=安裝程式正在準備安裝 [name] 到您的電腦。
PreviousInstallNotCompleted=先前的程式安裝或解除安裝未完成，您需要重啟您的電腦以完成。%n%n在重啟電腦後，再次執行安裝程式以完成 [name] 的安裝。
CannotContinue=安裝程式不能繼續。請點選“取消”退出。
ApplicationsFound=以下應用程式正在使用將由安裝程式更新的檔案。建議您允許安裝程式自動關閉這些應用程式。
ApplicationsFound2=以下應用程式正在使用將由安裝程式更新的檔案。建議您允許安裝程式自動關閉這些應用程式。安裝完成後，安裝程式將嘗試重新啟動這些應用程式。
CloseApplications=自動關閉應用程式(&A)
DontCloseApplications=不要關閉應用程式(&D)
ErrorCloseApplications=安裝程式無法自動關閉所有應用程式。建議您在繼續之前，關閉所有在使用需要由安裝程式更新的檔案的應用程式。
PrepareToInstallNeedsRestart=安裝程式必須重啟您的計算機。計算機重啟後，請再次執行安裝程式以完成 [name] 的安裝。%n%n是否立即重新啟動？

; *** “正在安裝”嚮導頁
WizardInstalling=正在安裝
InstallingLabel=安裝程式正在安裝 [name] 到您的電腦，請稍候。

; *** “安裝完成”嚮導頁
FinishedHeadingLabel=[name] 安裝完成
FinishedLabelNoIcons=安裝程式已在您的電腦中安裝了 [name]。
FinishedLabel=安裝程式已在您的電腦中安裝了 [name]。您可以透過已安裝的快捷方式執行此應用程式。
ClickFinish=點選“完成”退出安裝程式。
FinishedRestartLabel=為完成 [name] 的安裝，安裝程式必須重新啟動您的電腦。要立即重啟嗎？
FinishedRestartMessage=為完成 [name] 的安裝，安裝程式必須重新啟動您的電腦。%n%n要立即重啟嗎？
ShowReadmeCheck=是，我想查閱自述檔案
YesRadio=是，立即重啟電腦(&Y)
NoRadio=否，稍後重啟電腦(&N)
; used for example as 'Run MyProg.exe'
RunEntryExec=執行 %1
; used for example as 'View Readme.txt'
RunEntryShellExec=查閱 %1

; *** “安裝程式需要下一張磁碟”提示
ChangeDiskTitle=安裝程式需要下一張磁碟
SelectDiskLabel2=請插入磁碟 %1 並點選“確定”。%n%n如果這個磁碟中的檔案可以在下列資料夾之外的資料夾中找到，請輸入正確的路徑或點選“瀏覽”。
PathLabel=路徑(&P)：
FileNotInDir2=“%2”中找不到檔案“%1”。請插入正確的磁碟或選擇其他資料夾。
SelectDirectoryLabel=請指定下一張磁碟的位置。

; *** 安裝階段訊息
SetupAborted=安裝程式未完成安裝。%n%n請修正這個問題並重新執行安裝程式。
AbortRetryIgnoreSelectAction=選擇操作
AbortRetryIgnoreRetry=重試(&T)
AbortRetryIgnoreIgnore=忽略錯誤並繼續(&I)
AbortRetryIgnoreCancel=關閉安裝程式
RetryCancelSelectAction=選擇操作
RetryCancelRetry=重試(&T)
RetryCancelCancel=取消(&C)

; *** 安裝狀態訊息
StatusClosingApplications=正在關閉應用程式...
StatusCreateDirs=正在建立目錄...
StatusExtractFiles=正在提取檔案...
StatusDownloadFiles=正在下載檔案...
StatusCreateIcons=正在建立快捷方式...
StatusCreateIniEntries=正在建立 INI 條目...
StatusCreateRegistryEntries=正在建立登錄檔條目...
StatusRegisterFiles=正在註冊檔案...
StatusSavingUninstall=正在儲存解除安裝資訊...
StatusRunProgram=正在完成安裝...
StatusRestartingApplications=正在重啟應用程式...
StatusRollback=正在撤銷更改...

; *** 其他錯誤
ErrorInternal2=內部錯誤：%1
ErrorFunctionFailedNoCode=%1 失敗
ErrorFunctionFailed=%1 失敗；錯誤程式碼 %2
ErrorFunctionFailedWithMessage=%1 失敗；錯誤程式碼 %2.%n%3
ErrorExecutingProgram=無法執行檔案：%n%1

; *** 登錄檔錯誤
ErrorRegOpenKey=開啟登錄檔項時出錯：%n%1\%2
ErrorRegCreateKey=建立登錄檔項時出錯：%n%1\%2
ErrorRegWriteKey=寫入登錄檔項時出錯：%n%1\%2

; *** INI 錯誤
ErrorIniEntry=在檔案“%1”中建立 INI 條目時出錯。

; *** 檔案複製錯誤
FileAbortRetryIgnoreSkipNotRecommended=跳過此檔案(&S) (不推薦)
FileAbortRetryIgnoreIgnoreNotRecommended=忽略錯誤並繼續(&I) (不推薦)
SourceIsCorrupted=原始檔已損壞
SourceDoesntExist=原始檔“%1”不存在
SourceVerificationFailed=原始檔驗證失敗: %1
VerificationSignatureDoesntExist=簽名檔案“%1”不存在
VerificationSignatureInvalid=簽名檔案“%1”無效
VerificationKeyNotFound=簽名檔案“%1”使用了未知金鑰
VerificationFileNameIncorrect=檔名不正確
VerificationFileTagIncorrect=檔案標籤不正確
VerificationFileSizeIncorrect=檔案大小不正確
VerificationFileHashIncorrect=檔案雜湊值不正確
ExistingFileReadOnly2=無法替換現有檔案，它是隻讀的。
ExistingFileReadOnlyRetry=移除只讀屬性並重試(&R)
ExistingFileReadOnlyKeepExisting=保留現有檔案(&K)
ErrorReadingExistingDest=嘗試讀取現有檔案時出錯：
FileExistsSelectAction=選擇操作
FileExists2=檔案已經存在。
FileExistsOverwriteExisting=覆蓋已存在的檔案(&O)
FileExistsKeepExisting=保留現有的檔案(&K)
FileExistsOverwriteOrKeepAll=為所有衝突檔案執行此操作(&D)
ExistingFileNewerSelectAction=選擇操作
ExistingFileNewer2=現有的檔案比安裝程式將要安裝的檔案還要新。
ExistingFileNewerOverwriteExisting=覆蓋已存在的檔案(&O)
ExistingFileNewerKeepExisting=保留現有的檔案(&K) (推薦)
ExistingFileNewerOverwriteOrKeepAll=為所有衝突檔案執行此操作(&D)
ErrorChangingAttr=嘗試更改下列現有檔案的屬性時出錯：
ErrorCreatingTemp=嘗試在目標目錄建立檔案時出錯：
ErrorReadingSource=嘗試讀取下列原始檔時出錯：
ErrorCopying=嘗試複製下列檔案時出錯：
ErrorDownloading=下載檔案時出錯：
ErrorExtracting=解壓壓縮檔案時出錯：
ErrorReplacingExistingFile=嘗試替換現有檔案時出錯：
ErrorRestartReplace=重啟並替換失敗：
ErrorRenamingTemp=嘗試重新命名下列目標目錄中的一個檔案時出錯：
ErrorRegisterServer=無法註冊 DLL/OCX：%1
ErrorRegSvr32Failed=RegSvr32 失敗；退出程式碼 %1
ErrorRegisterTypeLib=無法註冊類庫：%1

; *** 解除安裝顯示名字標記
; used for example as 'My Program (32-bit)'
UninstallDisplayNameMark=%1 (%2)
; used for example as 'My Program (32-bit, All users)'
UninstallDisplayNameMarks=%1 (%2, %3)
UninstallDisplayNameMark32Bit=32 位
UninstallDisplayNameMark64Bit=64 位
UninstallDisplayNameMarkAllUsers=所有使用者
UninstallDisplayNameMarkCurrentUser=當前使用者

; *** 安裝後錯誤
ErrorOpeningReadme=嘗試開啟自述檔案時出錯。
ErrorRestartingComputer=安裝程式無法重啟電腦，請手動重啟。

; *** 解除安裝訊息
UninstallNotFound=檔案“%1”不存在。無法解除安裝。
UninstallOpenError=檔案“%1”不能被開啟。無法解除安裝。
UninstallUnsupportedVer=此版本的解除安裝程式無法識別解除安裝日誌檔案“%1”的格式。無法解除安裝
UninstallUnknownEntry=解除安裝日誌中遇到一個未知條目 (%1)
ConfirmUninstall=您確認要完全移除 %1 及其所有元件嗎？
UninstallOnlyOnWin64=僅允許在 64 位 Windows 中解除安裝此程式。
OnlyAdminCanUninstall=僅使用管理員許可權的使用者能完成此解除安裝。
UninstallStatusLabel=正在從您的電腦中移除 %1，請稍候。
UninstalledAll=已順利從您的電腦中移除 %1。
UninstalledMost=%1 解除安裝完成。%n%n有部分內容未能被刪除，但您可以手動刪除它們。
UninstalledAndNeedsRestart=為完成 %1 的解除安裝，需要重啟您的電腦。%n%n立即重啟電腦嗎？
UninstallDataCorrupted=檔案“%1”已損壞。無法解除安裝

; *** 解除安裝狀態訊息
ConfirmDeleteSharedFileTitle=刪除共享的檔案嗎？
ConfirmDeleteSharedFile2=系統表示下列共享的檔案已不有其他程式使用。您希望解除安裝程式刪除這些共享的檔案嗎？%n%n如果刪除這些檔案，但仍有程式在使用這些檔案，則這些程式可能出現異常。如果您不能確定，請選擇“否”，在系統中保留這些檔案以免引發問題。
SharedFileNameLabel=檔名：
SharedFileLocationLabel=位置：
WizardUninstalling=解除安裝狀態
StatusUninstalling=正在解除安裝 %1...

; *** Shutdown block reasons
ShutdownBlockReasonInstallingApp=正在安裝 %1。
ShutdownBlockReasonUninstallingApp=正在解除安裝 %1。

; The custom messages below aren't used by Setup itself, but if you make
; use of them in your scripts, you'll want to translate them.

[CustomMessages]

NameAndVersion=%1 版本 %2
AdditionalIcons=附加快捷方式：
CreateDesktopIcon=建立桌面快捷方式(&D)
CreateQuickLaunchIcon=建立快速啟動欄快捷方式(&Q)
ProgramOnTheWeb=%1 網站
UninstallProgram=解除安裝 %1
LaunchProgram=執行 %1
AssocFileExtension=將 %2 副檔名與 %1 建立關聯(&A)
AssocingFileExtension=正在將 %2 副檔名與 %1 建立關聯...
AutoStartProgramGroupDescription=啟動：
AutoStartProgram=自動啟動 %1
AddonHostProgramNotFound=您選擇的資料夾中無法找到 %1。%n%n您要繼續嗎？
