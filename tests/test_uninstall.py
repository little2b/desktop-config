import importlib.util,tempfile,unittest,io
from unittest.mock import patch,MagicMock
from pathlib import Path
from types import SimpleNamespace
spec=importlib.util.spec_from_file_location('uninstall',Path(__file__).resolve().parents[1] / 'lib/nyx-dock/uninstall-app.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
class ResolverTest(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
  self.local=Path(self.temp.name)/'local';self.system=Path(self.temp.name)/'system'
  self.local.mkdir();self.system.mkdir();self.calls=[]
  self.manager=patch.object(m.shutil,'which',side_effect=lambda name: '/usr/bin/rpm' if name=='rpm' else None)
  self.manager.start();self.addCleanup(self.manager.stop)
 def desktop(self,base,id,extra=''):
  p=base/(id+'.desktop');p.write_text('[Desktop Entry]\nType=Application\nName=Test\nExec=/does-not-exist\n'+extra);return p
 def fake(self,args):
  self.calls.append(args)
  if args[0]=='/usr/bin/flatpak':return SimpleNamespace(returncode=0,stdout='org.example.App\tuser\n')
  owned=args[-1].startswith(str(self.system))
  return SimpleNamespace(returncode=0 if owned else 1,stdout='test-package\n' if owned else '')
 def test_user_override_resolves_packaged_entry(self):
  self.desktop(self.local,'app');self.desktop(self.system,'app')
  info=m.resolve('app',[self.local,self.system],self.fake)
  self.assertEqual(info['provider'],'rpm');self.assertEqual(info['package'],'test-package')
  self.assertEqual(m.removal_command(info),['/usr/bin/pkexec','/usr/bin/dnf','remove','--','test-package'])
 def test_web_app_never_removes_browser(self):
  p=self.desktop(self.local,'web');p.write_text('[Desktop Entry]\nType=Application\nName=Web\nExec=google-chrome --app-id=abc\n')
  info=m.resolve('web',[self.local],self.fake)
  self.assertEqual(info['provider'],'web');self.assertIsNone(m.removal_command(info));self.assertFalse(self.calls)
 def test_flatpak_scopes_exact_installation(self):
  self.desktop(self.local,'org.example.App','X-Flatpak=org.example.App\n')
  info=m.resolve('org.example.App',[self.local],self.fake)
  self.assertEqual(m.removal_command(info),['/usr/bin/flatpak','uninstall','--user','--','org.example.App'])
 def test_manual_app_no_removal_command(self):
  self.desktop(self.local,'manual')
  self.assertIsNone(m.removal_command(m.resolve('manual',[self.local],self.fake)))
 def test_interpreter_is_not_app_package(self):
  self.assertIsNone(m.executable('/usr/bin/python3 /tmp/example.py'))
  self.assertIsNone(m.executable('env FOO=bar /usr/bin/bash -c whatever'))
 def test_traversal_rejected(self):
  with self.assertRaises(ValueError):m.resolve('../app',[self.local],self.fake)
 def test_duplicate_flatpak_installation_rejected(self):
  self.desktop(self.local,'org.example.App','X-Flatpak=org.example.App\n')
  def both(args):return SimpleNamespace(returncode=0,stdout='org.example.App\tuser\norg.example.App\tsystem\n')
  with self.assertRaises(ValueError):m.resolve('org.example.App',[self.local],both)
 def test_confirmation_not_bypassed(self):
  for info in [{'provider':'rpm','package':'test-package'},{'provider':'flatpak','installation':'system','package':'org.example.App'}]:
   args=m.removal_command(info);self.assertNotIn('-y',args);self.assertNotIn('--noninteractive',args);self.assertNotIn('--delete-data',args)
 def main_flow(self, code, installed):
  info={'id':'test','name':'Test','provider':'rpm','package':'test-package'}
  with patch.object(m,'resolve',return_value=info), patch.object(m.subprocess,'run',return_value=SimpleNamespace(returncode=code)), patch.object(m,'still_installed',return_value=installed), patch.object(m,'cleanup_launcher') as cleanup, patch.object(m.sys,'argv',['helper','test']), patch.object(m.sys,'stdin',MagicMock(isatty=lambda:True)), patch('builtins.input',return_value=''), patch.object(m.sys,'stdout',io.StringIO()):
   m.main()
   return cleanup.called
 def test_cancel_does_not_remove_launchers_or_pins(self):
  self.assertFalse(self.main_flow(1,True))
 def test_zero_exit_without_removal_does_not_cleanup(self):
  self.assertFalse(self.main_flow(0,True))
 def test_cleanup_only_after_verified_removal(self):
  self.assertTrue(self.main_flow(0,False))
 def test_arch_package_lookup_and_interactive_removal(self):
  self.desktop(self.system,'arch-app')
  with patch.object(m.shutil,'which',side_effect=lambda name: '/usr/bin/pacman' if name=='pacman' else None):
   info=m.resolve('arch-app',[self.system],self.fake)
  self.assertEqual(info['provider'],'pacman')
  self.assertEqual(self.calls[-1],['/usr/bin/pacman','-Qqo','--',str(self.system/'arch-app.desktop')])
  self.assertEqual(m.removal_command(info),['/usr/bin/pkexec','/usr/bin/pacman','-R','--','test-package'])
  self.assertNotIn('--noconfirm',m.removal_command(info))
if __name__ == '__main__':
 unittest.main()
